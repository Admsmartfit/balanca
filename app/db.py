"""Persistência SQLite — perfis e histórico de medições (RF07).

Sem ORM: o volume de dados de uma balança doméstica (poucos perfis, algumas
medições por dia) não justifica a complexidade extra. Todas as chamadas
acontecem na mesma thread da loop de eventos do FastAPI (endpoints `async
def`, sem `run_in_threadpool`), então uma única conexão sqlite3 é segura sem
locking adicional.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT_DIR

DB_PATH = ROOT_DIR / "miscale.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    height_cm REAL NOT NULL,
    age INTEGER NOT NULL,
    sex TEXT NOT NULL CHECK (sex IN ('male', 'female')),
    algorithm TEXT NOT NULL DEFAULT 'xiaomi' CHECK (algorithm IN ('xiaomi', 'science')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS idx_measurements_profile_time
    ON measurements(profile_id, recorded_at);
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


class InvalidProfile(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Profile:
    id: int
    name: str
    height_cm: float
    age: int
    sex: str
    algorithm: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "height_cm": self.height_cm,
            "age": self.age,
            "sex": self.sex,
            "algorithm": self.algorithm,
        }


def _validate_profile_fields(*, name: str, height_cm: float, age: int, sex: str, algorithm: str) -> None:
    if not name or not name.strip():
        raise InvalidProfile("name não pode ser vazio")
    if not (100 <= height_cm <= 220):
        raise InvalidProfile("height_cm deve estar entre 100 e 220")
    if not (1 <= age <= 99):
        raise InvalidProfile("age deve estar entre 1 e 99")
    if sex not in VALID_SEXES:
        raise InvalidProfile("sex deve ser 'male' ou 'female'")
    if algorithm not in VALID_ALGORITHMS:
        raise InvalidProfile("algorithm deve ser 'xiaomi' ou 'science'")


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Adiciona colunas novas a bancos criados por versões anteriores (Fases 1/2)."""
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(measurements)")}
        if "body_score" not in existing:
            self._conn.execute("ALTER TABLE measurements ADD COLUMN body_score REAL")

    def close(self) -> None:
        self._conn.close()

    # -- Perfis -----------------------------------------------------------

    def list_profiles(self) -> list[Profile]:
        rows = self._conn.execute("SELECT * FROM profiles ORDER BY name").fetchall()
        return [_row_to_profile(row) for row in rows]

    def get_profile(self, profile_id: int) -> Profile | None:
        row = self._conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        return _row_to_profile(row) if row else None

    def create_profile(self, *, name: str, height_cm: float, age: int, sex: str, algorithm: str) -> Profile:
        _validate_profile_fields(name=name, height_cm=height_cm, age=age, sex=sex, algorithm=algorithm)
        try:
            cursor = self._conn.execute(
                "INSERT INTO profiles (name, height_cm, age, sex, algorithm, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name.strip(), height_cm, age, sex, algorithm, datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise InvalidProfile(f"já existe um perfil chamado '{name}'") from exc
        self._conn.commit()
        return self.get_profile(cursor.lastrowid)  # type: ignore[return-value]

    def update_profile(
        self, profile_id: int, *, name: str, height_cm: float, age: int, sex: str, algorithm: str
    ) -> Profile:
        _validate_profile_fields(name=name, height_cm=height_cm, age=age, sex=sex, algorithm=algorithm)
        if self.get_profile(profile_id) is None:
            raise InvalidProfile(f"perfil {profile_id} não existe")
        try:
            self._conn.execute(
                "UPDATE profiles SET name = ?, height_cm = ?, age = ?, sex = ?, algorithm = ? WHERE id = ?",
                (name.strip(), height_cm, age, sex, algorithm, profile_id),
            )
        except sqlite3.IntegrityError as exc:
            raise InvalidProfile(f"já existe um perfil chamado '{name}'") from exc
        self._conn.commit()
        return self.get_profile(profile_id)  # type: ignore[return-value]

    def delete_profile(self, profile_id: int) -> None:
        self._conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        self._conn.commit()

    def last_weight_by_profile(self) -> dict[int, float]:
        """Peso da medição mais recente de cada perfil — usado pelo RF08."""
        rows = self._conn.execute(
            "SELECT profile_id, weight_kg FROM measurements "
            "WHERE id IN (SELECT MAX(id) FROM measurements WHERE profile_id IS NOT NULL GROUP BY profile_id)"
        ).fetchall()
        return {row["profile_id"]: row["weight_kg"] for row in rows}

    # -- Medições -----------------------------------------------------------

    def insert_measurement(
        self,
        *,
        profile_id: int,
        weight_kg: float,
        unit: str,
        impedance_ohm: float | None,
        algorithm: str | None,
        metrics: dict | None,
    ) -> int:
        metrics = metrics or {}
        columns = ["profile_id", "recorded_at", "weight_kg", "unit", "impedance_ohm", "algorithm", *METRIC_COLUMNS]
        values = [
            profile_id,
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

    def list_measurements(self, profile_id: int, *, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM measurements WHERE profile_id = ? ORDER BY recorded_at DESC LIMIT ?",
            (profile_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def export_measurements(self, profile_id: int, fmt: str) -> tuple[str, str]:
        """Retorna (conteúdo, content_type) para exportação CSV/JSON (RF07)."""
        rows = list(reversed(self.list_measurements(profile_id, limit=100_000)))

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


def _row_to_profile(row: sqlite3.Row) -> Profile:
    return Profile(
        id=row["id"],
        name=row["name"],
        height_cm=row["height_cm"],
        age=row["age"],
        sex=row["sex"],
        algorithm=row["algorithm"],
    )
