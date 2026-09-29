"""Testes da camada de persistência — clientes, admins e medições."""

import sqlite3

import pytest

from app.db import Database, InvalidAdmin, InvalidClient


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


# Schema da era Fases 1-3 (antes do sistema de cadastro/PIN) — measurements
# tinha profile_id, não client_id. Usado para testar a migração de bancos
# reais que os usuários já têm rodando.
_LEGACY_SCHEMA = """
CREATE TABLE profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    height_cm REAL NOT NULL,
    age INTEGER NOT NULL,
    sex TEXT NOT NULL,
    algorithm TEXT NOT NULL DEFAULT 'xiaomi',
    created_at TEXT NOT NULL
);
CREATE TABLE measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    recorded_at TEXT NOT NULL,
    weight_kg REAL NOT NULL,
    unit TEXT NOT NULL,
    impedance_ohm REAL,
    algorithm TEXT,
    bmi REAL, fat_percentage REAL, water_percentage REAL, bone_mass_kg REAL,
    muscle_mass_kg REAL, visceral_fat REAL, bmr_kcal REAL, metabolic_age REAL,
    protein_percentage REAL, body_score REAL
);
CREATE INDEX idx_measurements_profile_time ON measurements(profile_id, recorded_at);
"""


def test_opening_a_legacy_pre_auth_database_does_not_crash(tmp_path):
    legacy_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO profiles (name, height_cm, age, sex, algorithm, created_at) "
        "VALUES ('Alice', 165, 28, 'female', 'xiaomi', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO measurements (profile_id, recorded_at, weight_kg, unit, bmi) "
        "VALUES (1, '2026-01-01T00:00:00+00:00', 60.0, 'kg', 22.0)"
    )
    conn.commit()
    conn.close()

    database = Database(legacy_path)
    try:
        # o schema novo aplicou sem erro, e a tabela antiga foi preservada, não apagada
        assert database.list_clients() == []
        legacy_rows = database._conn.execute("SELECT * FROM measurements_legacy_v3").fetchall()
        assert len(legacy_rows) == 1
        assert legacy_rows[0]["weight_kg"] == 60.0

        # a nova tabela measurements (client_id) existe e funciona normalmente
        client = database.create_client(
            full_name="Bob", document="12345678909", birthdate="1990-01-01", sex="male",
            height_cm=180, algorithm="xiaomi", pin="1234", accepted_terms=True,
        )
        database.insert_measurement(
            client_id=client.id, weight_kg=80.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
        )
        assert len(database.list_measurements(client.id)) == 1
    finally:
        database.close()


def _make_client(db, **overrides):
    fields = dict(
        full_name="Alice Souza",
        document="123.456.789-09",
        birthdate="1998-04-12",
        sex="female",
        height_cm=165,
        algorithm="xiaomi",
        pin="1234",
        accepted_terms=True,
    )
    fields.update(overrides)
    return db.create_client(**fields)


def test_create_and_list_clients(db):
    _make_client(db, full_name="Alice Souza", document="12345678909")
    _make_client(db, full_name="Bob Lima", document="98765432100")

    clients = db.list_clients()
    assert [c.full_name for c in clients] == ["Alice Souza", "Bob Lima"]


def test_document_is_normalized_and_unique(db):
    _make_client(db, document="123.456.789-09")
    with pytest.raises(InvalidClient):
        _make_client(db, document="12345678909", full_name="Outra Pessoa")


def test_create_client_requires_accepted_terms(db):
    with pytest.raises(InvalidClient):
        _make_client(db, accepted_terms=False)


def test_create_client_rejects_invalid_fields(db):
    with pytest.raises(InvalidClient):
        _make_client(db, height_cm=50)
    with pytest.raises(InvalidClient):
        _make_client(db, sex="other")
    with pytest.raises(InvalidClient):
        _make_client(db, algorithm="bogus")
    with pytest.raises(InvalidClient):
        _make_client(db, birthdate="2099-01-01")  # data no futuro


def test_client_age_is_computed_from_birthdate(db):
    client = _make_client(db, birthdate="2000-01-01")
    assert client.age >= 25  # este teste não vai sobreviver ao ano 2100, e tudo bem


def test_find_client_by_document(db):
    created = _make_client(db, document="12345678909")
    found = db.find_client_by_document("123.456.789-09")
    assert found is not None
    assert found.id == created.id
    assert db.find_client_by_document("00000000000") is None


def test_pin_verification(db):
    client = _make_client(db, pin="4321")
    assert db.verify_client_pin(client.id, "4321") is True
    assert db.verify_client_pin(client.id, "0000") is False


def test_reset_client_pin(db):
    client = _make_client(db, pin="1111")
    db.reset_client_pin(client.id, "2222")
    assert db.verify_client_pin(client.id, "1111") is False
    assert db.verify_client_pin(client.id, "2222") is True


def test_update_client(db):
    client = _make_client(db)
    updated = db.update_client(
        client.id,
        full_name="Alice S. Souza",
        document=client.document,
        birthdate=client.birthdate,
        sex=client.sex,
        height_cm=170,
        algorithm="science",
    )
    assert updated.full_name == "Alice S. Souza"
    assert updated.height_cm == 170
    assert updated.algorithm == "science"


def test_delete_client_removes_it(db):
    client = _make_client(db)
    db.delete_client(client.id)
    assert db.list_clients() == []


def test_insert_and_list_measurements(db):
    client = _make_client(db)
    db.insert_measurement(
        client_id=client.id,
        weight_kg=60.0,
        unit="kg",
        impedance_ohm=550.0,
        algorithm="xiaomi",
        metrics={"bmi": 22.0, "fat_percentage": 25.0, "body_score": 80.0},
    )
    measurements = db.list_measurements(client.id)
    assert len(measurements) == 1
    assert measurements[0]["weight_kg"] == 60.0
    assert measurements[0]["bmi"] == 22.0
    assert measurements[0]["body_score"] == 80.0


def test_last_weight_by_client_tracks_most_recent(db):
    client = _make_client(db)
    db.insert_measurement(
        client_id=client.id, weight_kg=61.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    db.insert_measurement(
        client_id=client.id, weight_kg=60.5, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    assert db.last_weight_by_client() == {client.id: 60.5}


def test_export_csv_and_json(db):
    client = _make_client(db)
    db.insert_measurement(
        client_id=client.id, weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi",
        metrics={"bmi": 22.0},
    )

    csv_content, csv_type = db.export_measurements(client.id, "csv")
    assert csv_type == "text/csv"
    assert "weight_kg" in csv_content
    assert "60.0" in csv_content

    json_content, json_type = db.export_measurements(client.id, "json")
    assert json_type == "application/json"
    assert '"weight_kg": 60.0' in json_content


# -- Administradores --------------------------------------------------------


def test_create_and_authenticate_admin(db):
    admin = db.create_admin(email="Admin@Exemplo.com", password="senhasegura123")
    assert admin.email == "admin@exemplo.com"  # normalizado para minúsculas

    found = db.get_admin_by_email("admin@exemplo.com")
    assert found is not None
    assert found[0].id == admin.id


def test_create_admin_rejects_invalid_email(db):
    with pytest.raises(InvalidAdmin):
        db.create_admin(email="não-é-email", password="senhasegura123")


def test_create_admin_rejects_weak_password(db):
    with pytest.raises(InvalidAdmin):
        db.create_admin(email="admin@exemplo.com", password="123")


def test_create_admin_rejects_duplicate_email(db):
    db.create_admin(email="admin@exemplo.com", password="senhasegura123")
    with pytest.raises(InvalidAdmin):
        db.create_admin(email="admin@exemplo.com", password="outrasenha123")


def test_count_admins(db):
    assert db.count_admins() == 0
    db.create_admin(email="admin@exemplo.com", password="senhasegura123")
    assert db.count_admins() == 1


# -- Fotos de evolução -------------------------------------------------------


def test_add_and_list_progress_photos(db):
    client = _make_client(db)
    db.add_progress_photo(client_id=client.id, file_path="data/photos/1.jpg", content_type="image/jpeg")
    db.add_progress_photo(client_id=client.id, file_path="data/photos/2.jpg", content_type="image/jpeg")

    photos = db.list_progress_photos(client.id)
    assert len(photos) == 2
    assert photos[0].client_id == client.id
    assert photos[0].content_type == "image/jpeg"


def test_delete_progress_photo(db):
    client = _make_client(db)
    photo = db.add_progress_photo(client_id=client.id, file_path="data/photos/1.jpg", content_type="image/jpeg")
    db.delete_progress_photo(photo.id)
    assert db.list_progress_photos(client.id) == []


def test_progress_photos_are_deleted_when_client_is_deleted(db):
    client = _make_client(db)
    db.add_progress_photo(client_id=client.id, file_path="data/photos/1.jpg", content_type="image/jpeg")
    db.delete_client(client.id)
    assert db.list_progress_photos(client.id) == []


def test_delete_client_removes_photo_files_from_disk(db, tmp_path):
    client = _make_client(db)
    photo_path = tmp_path / "photo.jpg"
    thumb_path = tmp_path / "thumb.jpg"
    photo_path.write_bytes(b"fake-jpeg")
    thumb_path.write_bytes(b"fake-thumb")
    measurement_id = db.insert_measurement(
        client_id=client.id, weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    db.upsert_measurement_photo(
        client_id=client.id,
        measurement_id=measurement_id,
        pose_type="front",
        file_path=str(photo_path),
        thumb_path=str(thumb_path),
        content_type="image/jpeg",
    )

    db.delete_client(client.id)

    assert not photo_path.exists()
    assert not thumb_path.exists()


# -- PRD v3 Etapa 1: migração real, consentimento de imagem, fotos por pose -----


def test_a_pre_stage1_database_migrates_without_crashing(tmp_path):
    """Um banco criado pela versão anterior (sem schema_meta, sem as colunas novas)
    precisa subir sem erro e ganhar as colunas/índices novos — não pode travar como
    aconteceu com a migração de measurements na Fase 3→autenticação."""
    pre_stage1_path = tmp_path / "pre-stage1.db"
    conn = sqlite3.connect(pre_stage1_path)
    conn.executescript(
        """
        CREATE TABLE clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL, document TEXT NOT NULL UNIQUE, birthdate TEXT NOT NULL,
            sex TEXT NOT NULL, height_cm REAL NOT NULL, algorithm TEXT NOT NULL DEFAULT 'xiaomi',
            pin_hash TEXT NOT NULL, accepted_terms_at TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
            recorded_at TEXT NOT NULL, weight_kg REAL NOT NULL, unit TEXT NOT NULL,
            impedance_ohm REAL, algorithm TEXT, bmi REAL, fat_percentage REAL, water_percentage REAL,
            bone_mass_kg REAL, muscle_mass_kg REAL, visceral_fat REAL, bmr_kcal REAL,
            metabolic_age REAL, protein_percentage REAL, body_score REAL
        );
        CREATE TABLE progress_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            taken_at TEXT NOT NULL, file_path TEXT NOT NULL, content_type TEXT NOT NULL
        );
        INSERT INTO clients (full_name, document, birthdate, sex, height_cm, pin_hash, accepted_terms_at, created_at)
        VALUES ('Carla', '11122233344', '1990-01-01', 'female', 168, 'x', '2026-01-01', '2026-01-01');
        INSERT INTO progress_photos (client_id, taken_at, file_path, content_type)
        VALUES (1, '2026-01-01', 'data/photos/old.jpg', 'image/jpeg');
        """
    )
    conn.commit()
    conn.close()

    database = Database(pre_stage1_path)
    try:
        columns = {row["name"] for row in database._conn.execute("PRAGMA table_info(progress_photos)")}
        assert {"measurement_id", "pose_type", "thumb_path", "source"} <= columns
        client_columns = {row["name"] for row in database._conn.execute("PRAGMA table_info(clients)")}
        assert "photo_consent_at" in client_columns

        # dados antigos preservados, com os defaults certos pras colunas novas
        photos = database.list_progress_photos(1)
        assert len(photos) == 1
        assert photos[0].source == "admin"
        assert photos[0].pose_type is None

        assert database.get_photo_prompt_min_days() == 15  # app_settings migrou e tem o default certo

        version = database._conn.execute("SELECT version FROM schema_meta").fetchone()["version"]
        assert version == 3
    finally:
        database.close()


def test_photo_consent_grant_preserves_first_timestamp_and_revoke_clears_it(db):
    client = _make_client(db)
    assert client.photo_consent_at is None
    assert client.has_photo_consent is False

    db.set_photo_consent(client.id, True)
    first_grant = db.get_client(client.id).photo_consent_at
    assert first_grant is not None

    db.set_photo_consent(client.id, True)  # conceder de novo não deve trocar a data original
    assert db.get_client(client.id).photo_consent_at == first_grant

    db.set_photo_consent(client.id, False)
    revoked = db.get_client(client.id)
    assert revoked.photo_consent_at is None
    assert revoked.has_photo_consent is False


def test_create_and_update_client_accept_photo_consent(db):
    client = _make_client(db, photo_consent=True)
    assert client.has_photo_consent is True

    updated = db.update_client(
        client.id,
        full_name=client.full_name,
        document=client.document,
        birthdate=client.birthdate,
        sex=client.sex,
        height_cm=client.height_cm,
        algorithm=client.algorithm,
        photo_consent=False,
    )
    assert updated.has_photo_consent is False


def test_upsert_measurement_photo_replaces_same_pose_instead_of_duplicating(db):
    client = _make_client(db)
    measurement_id = db.insert_measurement(
        client_id=client.id, weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )

    photo1, old1 = db.upsert_measurement_photo(
        client_id=client.id, measurement_id=measurement_id, pose_type="front",
        file_path="data/photos/1/front-a.jpg", thumb_path="data/photos/1/front-a-thumb.jpg",
        content_type="image/jpeg",
    )
    assert old1 == []

    photo2, old2 = db.upsert_measurement_photo(
        client_id=client.id, measurement_id=measurement_id, pose_type="front",
        file_path="data/photos/1/front-b.jpg", thumb_path="data/photos/1/front-b-thumb.jpg",
        content_type="image/jpeg",
    )
    assert old2 == ["data/photos/1/front-a.jpg", "data/photos/1/front-a-thumb.jpg"]
    assert photo2.id == photo1.id  # mesma linha, atualizada — não uma segunda

    photos = db.list_progress_photos(client.id)
    assert len(photos) == 1
    assert photos[0].file_path == "data/photos/1/front-b.jpg"


def test_latest_photos_by_pose_returns_the_most_recent_not_an_arbitrary_row(db):
    client = _make_client(db)
    m1 = db.insert_measurement(
        client_id=client.id, weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    m2 = db.insert_measurement(
        client_id=client.id, weight_kg=59.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    db.upsert_measurement_photo(
        client_id=client.id, measurement_id=m1, pose_type="front",
        file_path="old-front.jpg", thumb_path=None, content_type="image/jpeg",
    )
    db.upsert_measurement_photo(
        client_id=client.id, measurement_id=m2, pose_type="front",
        file_path="new-front.jpg", thumb_path=None, content_type="image/jpeg",
    )

    latest = db.latest_photos_by_pose(client.id)
    assert latest["front"].file_path == "new-front.jpg"


def test_first_and_latest_measurement_with_photos(db):
    client = _make_client(db)
    m_no_photo = db.insert_measurement(
        client_id=client.id, weight_kg=62.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    m_first_photo = db.insert_measurement(
        client_id=client.id, weight_kg=61.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    m_latest_photo = db.insert_measurement(
        client_id=client.id, weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    db.upsert_measurement_photo(
        client_id=client.id, measurement_id=m_first_photo, pose_type="front",
        file_path="a.jpg", thumb_path=None, content_type="image/jpeg",
    )
    db.upsert_measurement_photo(
        client_id=client.id, measurement_id=m_latest_photo, pose_type="front",
        file_path="b.jpg", thumb_path=None, content_type="image/jpeg",
    )

    assert db.first_measurement_with_photos(client.id)["id"] == m_first_photo
    assert db.latest_measurement_with_photos(client.id)["id"] == m_latest_photo
    assert m_no_photo != m_first_photo  # confirma que a medição sem foto não é a "primeira com foto"


def test_measurement_with_photos_is_none_when_client_has_no_photographed_measurement(db):
    client = _make_client(db)
    db.insert_measurement(
        client_id=client.id, weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    assert db.first_measurement_with_photos(client.id) is None
    assert db.latest_measurement_with_photos(client.id) is None


def test_latest_photo_taken_at_across_poses_and_measurements(db):
    client = _make_client(db)
    assert db.latest_photo_taken_at(client.id) is None

    m1 = db.insert_measurement(
        client_id=client.id, weight_kg=61.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    m2 = db.insert_measurement(
        client_id=client.id, weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    db.upsert_measurement_photo(
        client_id=client.id, measurement_id=m1, pose_type="front",
        file_path="old.jpg", thumb_path=None, content_type="image/jpeg",
    )
    older = db.latest_photo_taken_at(client.id)
    assert older is not None

    db.upsert_measurement_photo(
        client_id=client.id, measurement_id=m2, pose_type="side",
        file_path="new.jpg", thumb_path=None, content_type="image/jpeg",
    )
    newer = db.latest_photo_taken_at(client.id)
    assert newer >= older  # ISO 8601 ordena como string


# -- Configurações (app_settings) --------------------------------------------


def test_photo_prompt_min_days_defaults_to_15(db):
    assert db.get_photo_prompt_min_days() == 15


def test_photo_prompt_min_days_is_settable_and_persists(db):
    db.set_photo_prompt_min_days(7)
    assert db.get_photo_prompt_min_days() == 7

    db.set_photo_prompt_min_days(30)  # troca de novo — confirma o UPSERT, não uma segunda linha
    assert db.get_photo_prompt_min_days() == 30
    assert db._conn.execute("SELECT COUNT(*) AS n FROM app_settings").fetchone()["n"] == 1


def test_photo_prompt_min_days_rejects_negative(db):
    with pytest.raises(ValueError):
        db.set_photo_prompt_min_days(-1)


def test_generic_settings_get_and_set(db):
    assert db.get_setting("nao-existe") is None
    assert db.get_setting("nao-existe", "padrao") == "padrao"
    db.set_setting("chave", "valor")
    assert db.get_setting("chave") == "valor"
