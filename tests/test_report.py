"""Testes da geração de PDF do resultado (app/report.py)."""

from app.db import Client
from app.report import generate_and_save_report, generate_measurement_report, report_path_for

_CLIENT = Client(
    id=1, full_name="Alice Souza", document="12345678909", birthdate="1998-04-12",
    sex="female", height_cm=165, algorithm="xiaomi",
)

_FULL_MEASUREMENT = {
    "id": 1,
    "recorded_at": "2026-09-15T12:00:00+00:00",
    "weight_kg": 60.5,
    "unit": "kg",
    "impedance_ohm": 550,
    "algorithm": "xiaomi",
    "bmi": 22.2,
    "fat_percentage": 25.0,
    "water_percentage": 55.0,
    "bone_mass_kg": 2.3,
    "muscle_mass_kg": 43.0,
    "visceral_fat": 6.0,
    "bmr_kcal": 1400.0,
    "metabolic_age": 28.0,
    "protein_percentage": 18.0,
    "body_score": 78.0,
}

_WEIGHT_ONLY_MEASUREMENT = {
    **{k: None for k in _FULL_MEASUREMENT},
    "id": 2,
    "recorded_at": "2026-09-15T12:00:00+00:00",
    "weight_kg": 60.5,
    "unit": "kg",
}


def test_generates_valid_pdf_bytes_for_full_measurement():
    pdf_bytes = generate_measurement_report(_CLIENT, _FULL_MEASUREMENT)
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 500


def test_generates_valid_pdf_for_weight_only_measurement():
    pdf_bytes = generate_measurement_report(_CLIENT, _WEIGHT_ONLY_MEASUREMENT)
    assert pdf_bytes[:4] == b"%PDF"


def test_generate_and_save_report_writes_expected_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.report.REPORTS_DIR", tmp_path)
    path = generate_and_save_report(_CLIENT, _FULL_MEASUREMENT)
    assert path == report_path_for(_FULL_MEASUREMENT["id"])
    assert path.exists()
    assert path.read_bytes()[:4] == b"%PDF"
