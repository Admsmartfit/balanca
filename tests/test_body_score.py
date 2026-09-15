"""Testes do Body Score agregado (PRD seção 13, sugestão 1)."""

import pytest

from app.engine.common import BodyMetrics, BodyMetricsInput
from app.engine.body_score import compute_body_score


def _metrics(**overrides) -> BodyMetrics:
    base = dict(
        bmi=22.0,
        fat_percentage=15.0,
        water_percentage=60.0,
        bone_mass_kg=2.5,
        muscle_mass_kg=60.0,
        visceral_fat=5.0,
        bmr_kcal=1700.0,
        metabolic_age=30.0,
        protein_percentage=20.0,
    )
    base.update(overrides)
    return BodyMetrics(**base)


PERFECT_PROFILE = BodyMetricsInput(weight_kg=80, height_cm=175, age=30, sex="male", impedance_ohm=500)


def test_perfect_profile_scores_100():
    assert compute_body_score(PERFECT_PROFILE, _metrics()) == 100.0


def test_worst_case_clamps_at_floor_of_10():
    terrible = _metrics(
        bmi=13.0,
        fat_percentage=75.0,
        water_percentage=10.0,
        bone_mass_kg=0.5,
        muscle_mass_kg=10.0,
        visceral_fat=50.0,
        bmr_kcal=500.0,
        protein_percentage=5.0,
    )
    assert compute_body_score(PERFECT_PROFILE, terrible) == 10.0


def test_never_exceeds_valid_range_across_profiles():
    for sex in ("male", "female"):
        for age in (10, 17, 25, 45, 65, 90):
            for bmi in (13, 17, 22, 30, 40):
                data = BodyMetricsInput(weight_kg=70, height_cm=170, age=age, sex=sex, impedance_ohm=500)
                metrics = _metrics(bmi=bmi)
                score = compute_body_score(data, metrics)
                assert 10.0 <= score <= 100.0


def test_only_bmi_penalty_matches_hand_traced_value():
    # bmi=14.5 cai entre bmi_very_low(14) e bmi_low(15):
    # malus(14.5, 14, 15, 30, 15) + 15 = ((14.5-15)/(14-15))*(30-15) + 15 = 7.5 + 15 = 22.5
    score = compute_body_score(PERFECT_PROFILE, _metrics(bmi=14.5))
    assert score == pytest.approx(77.5)
