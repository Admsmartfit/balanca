"""Testes do motor Xiaomi (RNF07).

Duas frentes:

1. Paridade contra o código vendorizado original (``vendor/lolouk44_xiaomi_mi_scale``)
   — prova que o port em ``app/engine/xiaomi.py`` produz exatamente os mesmos
   números que a classe ``bodyMetrics`` de origem, para vários perfis.
2. RNF06 — leituras fora dos limites fisiológicos levantam ``OutOfRangeReading``
   em vez de derrubar o processo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

VENDOR_SRC = Path(__file__).resolve().parent.parent / "vendor" / "lolouk44_xiaomi_mi_scale" / "src"
sys.path.insert(0, str(VENDOR_SRC))
from Xiaomi_Scale_Body_Metrics import bodyMetrics  # noqa: E402  (path hack above)

from app.engine.xiaomi import BodyMetricsInput, OutOfRangeReading, compute_xiaomi_metrics  # noqa: E402

REFERENCE_PROFILES = [
    # weight_kg, height_cm, age, sex, impedance_ohm
    (70.0, 175.0, 30, "male", 480.0),
    (55.0, 160.0, 25, "female", 620.0),
    (95.0, 185.0, 45, "male", 350.0),
    (48.0, 152.0, 68, "female", 700.0),
    (110.0, 190.0, 22, "male", 300.0),
]


@pytest.mark.parametrize("weight_kg,height_cm,age,sex,impedance_ohm", REFERENCE_PROFILES)
def test_matches_vendored_reference(weight_kg, height_cm, age, sex, impedance_ohm):
    reference = bodyMetrics(weight_kg, height_cm, age, sex, impedance_ohm)
    result = compute_xiaomi_metrics(
        BodyMetricsInput(
            weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex, impedance_ohm=impedance_ohm
        )
    )

    assert result.bmi == pytest.approx(reference.getBMI(), abs=0.05)
    assert result.fat_percentage == pytest.approx(reference.getFatPercentage(), abs=0.05)
    assert result.water_percentage == pytest.approx(reference.getWaterPercentage(), abs=0.05)
    assert result.bone_mass_kg == pytest.approx(reference.getBoneMass(), abs=0.05)
    assert result.muscle_mass_kg == pytest.approx(reference.getMuscleMass(), abs=0.05)
    assert result.visceral_fat == pytest.approx(reference.getVisceralFat(), abs=0.05)
    assert result.bmr_kcal == pytest.approx(reference.getBMR(), abs=1.0)
    assert result.metabolic_age == pytest.approx(reference.getMetabolicAge(), abs=0.5)
    assert result.protein_percentage == pytest.approx(reference.getProteinPercentage(), abs=0.05)


@pytest.mark.parametrize(
    "weight_kg,height_cm,age,sex,impedance_ohm",
    [
        (5.0, 175.0, 30, "male", 480.0),  # peso abaixo de 10kg
        (250.0, 175.0, 30, "male", 480.0),  # peso acima de 200kg
        (70.0, 230.0, 30, "male", 480.0),  # altura acima de 220cm
        (70.0, 175.0, 105, "male", 480.0),  # idade acima de 99
        (70.0, 175.0, 30, "male", 3500.0),  # impedância acima de 3000 ohm
        (70.0, 175.0, 30, "male", 0.0),  # impedância zero (RNF06)
    ],
)
def test_out_of_range_reading_is_rejected(weight_kg, height_cm, age, sex, impedance_ohm):
    with pytest.raises(OutOfRangeReading):
        compute_xiaomi_metrics(
            BodyMetricsInput(
                weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex, impedance_ohm=impedance_ohm
            )
        )
