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
