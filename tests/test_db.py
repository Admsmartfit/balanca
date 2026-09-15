"""Testes da camada de persistência (RF07)."""

import pytest

from app.db import Database, InvalidProfile


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_create_and_list_profiles(db):
    db.create_profile(name="Alice", height_cm=165, age=28, sex="female", algorithm="xiaomi")
    db.create_profile(name="Bob", height_cm=180, age=35, sex="male", algorithm="science")

    profiles = db.list_profiles()
    assert [p.name for p in profiles] == ["Alice", "Bob"]


def test_duplicate_profile_name_is_rejected(db):
    db.create_profile(name="Alice", height_cm=165, age=28, sex="female", algorithm="xiaomi")
    with pytest.raises(InvalidProfile):
        db.create_profile(name="Alice", height_cm=170, age=30, sex="male", algorithm="xiaomi")


def test_invalid_profile_fields_are_rejected(db):
    with pytest.raises(InvalidProfile):
        db.create_profile(name="X", height_cm=50, age=28, sex="female", algorithm="xiaomi")
    with pytest.raises(InvalidProfile):
        db.create_profile(name="X", height_cm=165, age=28, sex="other", algorithm="xiaomi")
    with pytest.raises(InvalidProfile):
        db.create_profile(name="X", height_cm=165, age=28, sex="female", algorithm="bogus")


def test_insert_and_list_measurements(db):
    alice = db.create_profile(name="Alice", height_cm=165, age=28, sex="female", algorithm="xiaomi")

    db.insert_measurement(
        profile_id=alice.id,
        weight_kg=60.0,
        unit="kg",
        impedance_ohm=550.0,
        algorithm="xiaomi",
        metrics={"bmi": 22.0, "fat_percentage": 25.0},
    )

    measurements = db.list_measurements(alice.id)
    assert len(measurements) == 1
    assert measurements[0]["weight_kg"] == 60.0
    assert measurements[0]["bmi"] == 22.0


def test_last_weight_by_profile_tracks_most_recent(db):
    alice = db.create_profile(name="Alice", height_cm=165, age=28, sex="female", algorithm="xiaomi")

    db.insert_measurement(
        profile_id=alice.id, weight_kg=61.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )
    db.insert_measurement(
        profile_id=alice.id, weight_kg=60.5, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
    )

    assert db.last_weight_by_profile() == {alice.id: 60.5}


def test_export_csv_and_json(db):
    alice = db.create_profile(name="Alice", height_cm=165, age=28, sex="female", algorithm="xiaomi")
    db.insert_measurement(
        profile_id=alice.id, weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi",
        metrics={"bmi": 22.0},
    )

    csv_content, csv_type = db.export_measurements(alice.id, "csv")
    assert csv_type == "text/csv"
    assert "weight_kg" in csv_content
    assert "60.0" in csv_content

    json_content, json_type = db.export_measurements(alice.id, "json")
    assert json_type == "application/json"
    assert '"weight_kg": 60.0' in json_content


def test_delete_profile_removes_it(db):
    alice = db.create_profile(name="Alice", height_cm=165, age=28, sex="female", algorithm="xiaomi")
    db.delete_profile(alice.id)
    assert db.list_profiles() == []
