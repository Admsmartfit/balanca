"""Persistência SQLite — clientes, administradores e histórico de medições.

Sem ORM: o volume de dados de uma balança de uso único (poucos clientes,
algumas medições por dia) não justifica a complexidade extra. Todas as
chamadas acontecem na mesma thread da loop de eventos do FastAPI (endpoints
`async def`, sem `run_in_threadpool`), então uma única conexão sqlite3 é
segura sem locking adicional.

RNF02 (LGPD): criptografia em repouso do banco foi avaliada e adiada
deliberadamente — ver THIRD_PARTY_NOTICES.md. O arquivo `miscale.db` fica em
texto plano no disco; restrinja o acesso ao computador do servidor.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .config import ROOT_DIR
from .security import InvalidPassword, hash_password, hash_pin, normalize_document, validate_document, verify_pin

logger = logging.getLogger(__name__)

DB_PATH = ROOT_DIR / "miscale.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    document TEXT NOT NULL UNIQUE,
    birthdate TEXT NOT NULL,
    sex TEXT NOT NULL CHECK (sex IN ('male', 'female')),
    height_cm REAL NOT NULL,
    algorithm TEXT NOT NULL DEFAULT 'xiaomi' CHECK (algorithm IN ('xiaomi', 'science')),
    pin_hash TEXT NOT NULL,
    accepted_terms_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    recorded_at TEXT NOT NULL,
    weight_kg REAL NOT NULL,
    unit TEXT NOT NULL,
    impedance_ohm REAL,
    algorithm TEXT,
    bmi REAL,
    fat_percentage REAL,
    water_percentage REAL,
    bone_mass_kg REAL,
    muscle_mass_kg REAL,
    visceral_fat REAL,
    bmr_kcal REAL,
    metabolic_age REAL,
    protein_percentage REAL,
    body_score REAL
);
CREATE INDEX IF NOT EXISTS idx_measurements_client_time
    ON measurements(client_id, recorded_at);

CREATE TABLE IF NOT EXISTS progress_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    taken_at TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_type TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_progress_photos_client_time
    ON progress_photos(client_id, taken_at);
"""

METRIC_COLUMNS = (
    "bmi",
    "fat_percentage",
    "water_percentage",
    "bone_mass_kg",
    "muscle_mass_kg",
    "visceral_fat",
    "bmr_kcal",
    "metabolic_age",
    "protein_percentage",
    "body_score",
)

VALID_SEXES = {"male", "female"}
VALID_ALGORITHMS = {"xiaomi", "science"}


class InvalidClient(ValueError):
    pass


class InvalidAdmin(ValueError):
    pass


def _age_from_birthdate(birthdate: str) -> int:
    born = date.fromisoformat(birthdate)
    today = date.today()
    age = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        age -= 1
    return age


@dataclass(frozen=True, slots=True)
class Client:
    id: int
    full_name: str
    document: str
    birthdate: str
    sex: str
    height_cm: float
    algorithm: str

    @property
    def age(self) -> int:
        return _age_from_birthdate(self.birthdate)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "document": self.document,
            "birthdate": self.birthdate,
            "age": self.age,
            "sex": self.sex,
            "height_cm": self.height_cm,
            "algorithm": self.algorithm,
        }

    def as_public_dict(self) -> dict:
        """Versão exposta ao quiosque público — só o suficiente pra reconhecer o nome."""
        return {"id": self.id, "name": self._masked_name()}

    def _masked_name(self) -> str:
        parts = self.full_name.strip().split()
        if not parts:
            return "?"
        first = parts[0]
        last_initial = f" {parts[-1][0]}." if len(parts) > 1 else ""
        return f"{first}{last_initial}"


@dataclass(frozen=True, slots=True)
class Admin:
    id: int
    email: str


@dataclass(frozen=True, slots=True)
class ProgressPhoto:
    id: int
    client_id: int
    taken_at: str
    file_path: str
    content_type: str

    def as_dict(self) -> dict:
        return {"id": self.id, "client_id": self.client_id, "taken_at": self.taken_at, "content_type": self.content_type}


def _validate_client_fields(
    *, full_name: str, birthdate: str, sex: str, height_cm: float, algorithm: str
) -> None:
    if not full_name or not full_name.strip():
        raise InvalidClient("full_name não pode ser vazio")
    try:
        born = date.fromisoformat(birthdate)
    except ValueError as exc:
        raise InvalidClient("birthdate deve estar no formato YYYY-MM-DD") from exc
    if born > date.today():
        raise InvalidClient("birthdate não pode ser no futuro")
    if not (100 <= height_cm <= 220):
        raise InvalidClient("height_cm deve estar entre 100 e 220")
    if sex not in VALID_SEXES:
        raise InvalidClient("sex deve ser 'male' ou 'female'")
    if algorithm not in VALID_ALGORITHMS:
        raise InvalidClient("algorithm deve ser 'xiaomi' ou 'science'")


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate_legacy_schema()
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate_legacy_schema(self) -> None:
        """Abre espaço para o schema novo num banco de uma versão anterior.

        Nas Fases 1-3 (antes do sistema de cadastro/PIN), `measurements`
        tinha uma coluna `profile_id`, não `client_id`. `CREATE TABLE IF NOT
        EXISTS` não altera uma tabela que já existe — sem isso, o schema
        novo travava ao criar o índice de `client_id` (era só um comentário
        aqui antes, sem código de verdade; corrigido depois de um usuário
        bater nesse erro com um banco real da Fase 3).

        Não dá para migrar as linhas antigas: o perfil de antes não tinha
        documento/PIN/data de nascimento, exigidos por `clients` agora. A
        tabela antiga só é renomeada (preservada, não apagada) para abrir
        espaço para a nova.
        """
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(measurements)")}
        if columns and "client_id" not in columns:
            legacy_name = "measurements_legacy_v3"
            existing_tables = {
                row["name"] for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            suffix = 2
            while legacy_name in existing_tables:
                legacy_name = f"measurements_legacy_v3_{suffix}"
                suffix += 1
            self._conn.execute(f"ALTER TABLE measurements RENAME TO {legacy_name}")
            self._conn.commit()
            logger.warning(
                "banco com schema de uma versão anterior detectado — "
                "'measurements' renomeada para '%s' (dados preservados, não migrados)",
                legacy_name,
            )

    def _migrate(self) -> None:
        """Adiciona colunas novas a bancos criados por versões anteriores."""
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(measurements)")}
        if "body_score" not in existing:
            self._conn.execute("ALTER TABLE measurements ADD COLUMN body_score REAL")

    def close(self) -> None:
        self._conn.close()

    # -- Clientes -----------------------------------------------------------

    def list_clients(self) -> list[Client]:
        rows = self._conn.execute("SELECT * FROM clients ORDER BY full_name").fetchall()
        return [_row_to_client(row) for row in rows]

    def get_client(self, client_id: int) -> Client | None:
        row = self._conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return _row_to_client(row) if row else None

    def find_client_by_document(self, raw_document: str) -> Client | None:
        digits = normalize_document(raw_document)
        row = self._conn.execute("SELECT * FROM clients WHERE document = ?", (digits,)).fetchone()
        return _row_to_client(row) if row else None

    def create_client(
        self,
        *,
        full_name: str,
        document: str,
        birthdate: str,
        sex: str,
        height_cm: float,
        algorithm: str,
        pin: str,
        accepted_terms: bool,
    ) -> Client:
        _validate_client_fields(
            full_name=full_name, birthdate=birthdate, sex=sex, height_cm=height_cm, algorithm=algorithm
        )
        if not accepted_terms:
            raise InvalidClient("é preciso confirmar que o cliente aceitou os termos de uso dos dados (LGPD)")
        normalized_document = validate_document(document)
        pin_hash = hash_pin(pin)
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = self._conn.execute(
                "INSERT INTO clients "
                "(full_name, document, birthdate, sex, height_cm, algorithm, pin_hash, accepted_terms_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (full_name.strip(), normalized_document, birthdate, sex, height_cm, algorithm, pin_hash, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise InvalidClient(f"já existe um cliente cadastrado com o documento '{normalized_document}'") from exc
        self._conn.commit()
        return self.get_client(cursor.lastrowid)  # type: ignore[return-value]

    def update_client(
        self,
        client_id: int,
        *,
        full_name: str,
        document: str,
        birthdate: str,
        sex: str,
        height_cm: float,
        algorithm: str,
    ) -> Client:
        _validate_client_fields(
            full_name=full_name, birthdate=birthdate, sex=sex, height_cm=height_cm, algorithm=algorithm
        )
        if self.get_client(client_id) is None:
            raise InvalidClient(f"cliente {client_id} não existe")
        normalized_document = validate_document(document)
        try:
            self._conn.execute(
                "UPDATE clients SET full_name = ?, document = ?, birthdate = ?, sex = ?, height_cm = ?, algorithm = ? "
                "WHERE id = ?",
                (full_name.strip(), normalized_document, birthdate, sex, height_cm, algorithm, client_id),
            )
        except sqlite3.IntegrityError as exc:
            raise InvalidClient(f"já existe um cliente cadastrado com o documento '{normalized_document}'") from exc
        self._conn.commit()
        return self.get_client(client_id)  # type: ignore[return-value]

    def reset_client_pin(self, client_id: int, new_pin: str) -> None:
        """Reset de PIN pelo admin — substitui a recuperação por SMS/WhatsApp do PRD (decisão do produto)."""
        if self.get_client(client_id) is None:
            raise InvalidClient(f"cliente {client_id} não existe")
        self._conn.execute("UPDATE clients SET pin_hash = ? WHERE id = ?", (hash_pin(new_pin), client_id))
        self._conn.commit()

    def verify_client_pin(self, client_id: int, pin: str) -> bool:
        row = self._conn.execute("SELECT pin_hash FROM clients WHERE id = ?", (client_id,)).fetchone()
        return row is not None and verify_pin(pin, row["pin_hash"])

    def delete_client(self, client_id: int) -> None:
        self._conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        self._conn.commit()

    def last_weight_by_client(self) -> dict[int, float]:
        """Peso da medição mais recente de cada cliente — usado pelo motor de sugestão (RF04)."""
        rows = self._conn.execute(
            "SELECT client_id, weight_kg FROM measurements "
            "WHERE id IN (SELECT MAX(id) FROM measurements WHERE client_id IS NOT NULL GROUP BY client_id)"
        ).fetchall()
        return {row["client_id"]: row["weight_kg"] for row in rows}

    # -- Administradores (RF07 — RBAC) --------------------------------------

    def get_admin_by_email(self, email: str) -> tuple[Admin, str] | None:
        """Retorna (Admin, password_hash) ou None — o hash não entra no dataclass público."""
        row = self._conn.execute("SELECT * FROM admins WHERE email = ?", (email.strip().lower(),)).fetchone()
        if row is None:
            return None
        return Admin(id=row["id"], email=row["email"]), row["password_hash"]

    def get_admin(self, admin_id: int) -> Admin | None:
        row = self._conn.execute("SELECT * FROM admins WHERE id = ?", (admin_id,)).fetchone()
        return Admin(id=row["id"], email=row["email"]) if row else None

    def count_admins(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM admins").fetchone()["n"]

    def create_admin(self, *, email: str, password: str) -> Admin:
        email = email.strip().lower()
        if "@" not in email:
            raise InvalidAdmin("email inválido")
        try:
            password_hash = hash_password(password)
        except InvalidPassword as exc:
            raise InvalidAdmin(str(exc)) from exc
        try:
            cursor = self._conn.execute(
                "INSERT INTO admins (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise InvalidAdmin(f"já existe um administrador com o email '{email}'") from exc
        self._conn.commit()
        return self.get_admin(cursor.lastrowid)  # type: ignore[return-value]

    # -- Medições -----------------------------------------------------------

    def insert_measurement(
        self,
        *,
        client_id: int,
        weight_kg: float,
        unit: str,
        impedance_ohm: float | None,
        algorithm: str | None,
        metrics: dict | None,
    ) -> int:
        metrics = metrics or {}
        columns = ["client_id", "recorded_at", "weight_kg", "unit", "impedance_ohm", "algorithm", *METRIC_COLUMNS]
        values = [
            client_id,
            datetime.now(timezone.utc).isoformat(),
            weight_kg,
            unit,
            impedance_ohm,
            algorithm,
            *[metrics.get(col) for col in METRIC_COLUMNS],
        ]
        placeholders = ", ".join("?" for _ in columns)
        cursor = self._conn.execute(
            f"INSERT INTO measurements ({', '.join(columns)}) VALUES ({placeholders})", values
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def list_measurements(self, client_id: int, *, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM measurements WHERE client_id = ? ORDER BY recorded_at DESC LIMIT ?",
            (client_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_measurement(self, measurement_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM measurements WHERE id = ?", (measurement_id,)).fetchone()
        return dict(row) if row else None

    def export_measurements(self, client_id: int, fmt: str) -> tuple[str, str]:
        """Retorna (conteúdo, content_type) para exportação CSV/JSON (RF07 herdado da Fase 2)."""
        rows = list(reversed(self.list_measurements(client_id, limit=100_000)))

        if fmt == "json":
            return json.dumps(rows, indent=2), "application/json"

        if fmt == "csv":
            buffer = io.StringIO()
            columns = ["id", "recorded_at", "weight_kg", "unit", "impedance_ohm", "algorithm", *METRIC_COLUMNS]
            writer = csv.DictWriter(buffer, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col) for col in columns})
            return buffer.getvalue(), "text/csv"

        raise ValueError(f"formato de exportação desconhecido: {fmt!r}")

    # -- Fotos de evolução ("antes e depois") --------------------------------

    def add_progress_photo(self, *, client_id: int, file_path: str, content_type: str) -> ProgressPhoto:
        cursor = self._conn.execute(
            "INSERT INTO progress_photos (client_id, taken_at, file_path, content_type) VALUES (?, ?, ?, ?)",
            (client_id, datetime.now(timezone.utc).isoformat(), file_path, content_type),
        )
        self._conn.commit()
        return self.get_progress_photo(cursor.lastrowid)  # type: ignore[return-value,arg-type]

    def get_progress_photo(self, photo_id: int) -> ProgressPhoto | None:
        row = self._conn.execute("SELECT * FROM progress_photos WHERE id = ?", (photo_id,)).fetchone()
        return _row_to_photo(row) if row else None

    def list_progress_photos(self, client_id: int) -> list[ProgressPhoto]:
        rows = self._conn.execute(
            "SELECT * FROM progress_photos WHERE client_id = ? ORDER BY taken_at", (client_id,)
        ).fetchall()
        return [_row_to_photo(row) for row in rows]

    def delete_progress_photo(self, photo_id: int) -> None:
        self._conn.execute("DELETE FROM progress_photos WHERE id = ?", (photo_id,))
        self._conn.commit()


def _row_to_client(row: sqlite3.Row) -> Client:
    return Client(
        id=row["id"],
        full_name=row["full_name"],
        document=row["document"],
        birthdate=row["birthdate"],
        sex=row["sex"],
        height_cm=row["height_cm"],
        algorithm=row["algorithm"],
    )


def _row_to_photo(row: sqlite3.Row) -> ProgressPhoto:
    return ProgressPhoto(
        id=row["id"],
        client_id=row["client_id"],
        taken_at=row["taken_at"],
        file_path=row["file_path"],
        content_type=row["content_type"],
    )
