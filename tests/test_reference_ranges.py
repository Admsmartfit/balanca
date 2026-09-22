"""Testes das faixas de referência (medidor abaixo/normal/acima)."""

from app.engine.common import BodyMetricsInput
from app.engine.reference_ranges import (
    BMI_HIGH,
    BMI_LOW,
    VISCERAL_FAT_THRESHOLD,
    reference_ranges_for,
)

_DATA = BodyMetricsInput(weight_kg=70, height_cm=175, age=30, sex="male", impedance_ohm=500)


def test_bmi_range_is_who_standard_regardless_of_profile():
    ranges = reference_ranges_for(_DATA)
    assert ranges["bmi"].low == BMI_LOW
    assert ranges["bmi"].high == BMI_HIGH


def test_fat_percentage_range_matches_age_sex_table():
    male_30 = reference_ranges_for(BodyMetricsInput(weight_kg=70, height_cm=175, age=30, sex="male", impedance_ohm=500))
    female_30 = reference_ranges_for(
        BodyMetricsInput(weight_kg=60, height_cm=165, age=30, sex="female", impedance_ohm=500)
    )
    # tabela: 18-40 male=(11,17,22,27), female=(21,28,35,40) — ver body_score.py
    assert (male_30["fat_percentage"].low, male_30["fat_percentage"].high) == (17.0, 22.0)
    assert (female_30["fat_percentage"].low, female_30["fat_percentage"].high) == (28.0, 35.0)


def test_muscle_mass_range_matches_height_sex_table():
    tall_male = reference_ranges_for(
        BodyMetricsInput(weight_kg=80, height_cm=180, age=30, sex="male", impedance_ohm=500)
    )
    # altura >= 170 (masculino) -> (49.4, 59.5)
    assert (tall_male["muscle_mass_kg"].low, tall_male["muscle_mass_kg"].high) == (49.4, 59.5)


def test_visceral_fat_range_has_only_upper_threshold():
    ranges = reference_ranges_for(_DATA)
    assert ranges["visceral_fat"].low is None
    assert ranges["visceral_fat"].high == VISCERAL_FAT_THRESHOLD


def test_metrics_without_a_defined_range_are_absent():
    ranges = reference_ranges_for(_DATA)
    for metric in ("water_percentage", "bone_mass_kg", "protein_percentage", "bmr_kcal", "metabolic_age"):
        assert metric not in ranges
