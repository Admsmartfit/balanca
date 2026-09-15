"""Testes do motor científico (RF06, RNF07).

``vendor/dckiller51_bodymiscale`` é um componente Home Assistant — importar
seus módulos de verdade exigiria instalar o pacote `homeassistant` inteiro
só para rodar os testes, o que não vale o custo neste projeto. Em vez disso,
este arquivo transcreve as fórmulas de ``metrics/impedance.py``,
``metrics/weight.py`` e ``util.py`` (Apache-2.0, commit 684a5b9) de forma
independente — uma segunda passada sobre o mesmo texto-fonte lido em
``app/engine/science.py`` e ``app/engine/common.py`` — como conferência
cruzada contra erro de transcrição (constante trocada, sinal invertido,
limite de clamp errado etc.), já que não dá para comparar contra o módulo
original em runtime.
"""

from __future__ import annotations

import pytest

from app.engine.common import BodyMetricsInput, OutOfRangeReading
from app.engine.science import compute_science_metrics

_SCHOFIELD_MALE = (
    (59.512, -30.4), (22.706, 504.3), (17.686, 658.2),
    (15.057, 692.2), (11.472, 873.1), (11.711, 587.7),
)
_SCHOFIELD_FEMALE = (
    (58.317, -31.1), (20.315, 485.9), (13.384, 692.6),
    (14.818, 486.6), (8.126, 845.6), (9.082, 658.5),
)


def _expected(w: float, h: float, a: int, sex: str, z: float) -> dict:
    lbm = (h * 9.058 / 100.0) * (h / 100.0) + w * 0.32 + 12.226 - z * 0.0068 - a * 0.0542
    if sex == "female":
        lbm *= 0.84
    lbm = min(lbm, w * 0.98)

    fat = (w - lbm) / w * 100.0
    min_fat = 10.0 if sex == "female" else 5.0
    fat = max(min_fat, min(fat, 75.0))

    water = (100.0 - fat) * 0.73
    water = max(35.0, min(water, 73.0))

    base = 0.245691014 if sex == "female" else 0.18016894
    bone = (base - lbm * 0.05158) * -1
    bone = bone + 0.1 if bone > 2.2 else bone - 0.1
    if sex == "female" and bone > 5.1:
        bone = 8
    elif sex == "male" and bone > 5.2:
        bone = 8
    bone = max(0.5, min(bone, 8))

    muscle = w - (fat * 0.01 * w) - bone
    if sex == "female" and muscle >= 84:
        muscle = 120
    elif sex == "male" and muscle >= 93.5:
        muscle = 120
    muscle = max(10, min(muscle, 120))

    coeffs = _SCHOFIELD_FEMALE if sex == "female" else _SCHOFIELD_MALE
    idx = 0 if a < 3 else 1 if a < 10 else 2 if a < 18 else 3 if a < 30 else 4 if a < 60 else 5
    slope, constant = coeffs[idx]
    bmr = max(500, min(slope * w + constant, 5000))

    protein = lbm * 0.195 / w * 100.0
    protein = max(5, min(protein, 32))

    bmi = max(10, min(w / ((h / 100) ** 2), 90))

    if sex == "female":
        if w > (13 - (h * 0.5)) * -1:
            subsubcalc = ((h * 1.45) + (h * 0.1158) * h) - 120
            vfal = (w * 500 / subsubcalc - 6) + (a * 0.07)
        else:
            subcalc = 0.691 + (h * -0.0024) + (h * -0.0024)
            vfal = (((h * 0.027) - (subcalc * w)) * -1) + (a * 0.07) - a
    else:
        if h < w * 1.6:
            subcalc = ((h * 0.4) - (h * (h * 0.0826))) * -1
            vfal = ((w * 305) / (subcalc + 48)) - 2.9 + (a * 0.15)
        else:
            subcalc = 0.765 + h * -0.0015
            vfal = (((h * 0.143) - (w * subcalc)) * -1) + (a * 0.15) - 5.0
    visceral = max(1, min(vfal, 50))

    if sex == "female":
        metab = (h * -1.1165) + (w * 1.5784) + (a * 0.4615) + (z * 0.0415) + 83.2548
    else:
        metab = (h * -0.7471) + (w * 0.9161) + (a * 0.4184) + (z * 0.0517) + 54.2267
    metab = max(15, min(metab, 80))

    return {
        "bmi": bmi, "fat_percentage": fat, "water_percentage": water,
        "bone_mass_kg": bone, "muscle_mass_kg": muscle, "visceral_fat": visceral,
        "bmr_kcal": bmr, "metabolic_age": metab, "protein_percentage": protein,
    }


REFERENCE_PROFILES = [
    (70.0, 175.0, 30, "male", 480.0),
    (55.0, 160.0, 25, "female", 620.0),
    (95.0, 185.0, 45, "male", 350.0),
    (48.0, 152.0, 68, "female", 700.0),
    (110.0, 190.0, 22, "male", 300.0),
    (60.0, 168.0, 8, "female", 550.0),  # faixa etária infantil do Schofield
]


@pytest.mark.parametrize("weight_kg,height_cm,age,sex,impedance_ohm", REFERENCE_PROFILES)
def test_matches_hand_transcribed_formulas(weight_kg, height_cm, age, sex, impedance_ohm):
    expected = _expected(weight_kg, height_cm, age, sex, impedance_ohm)
    result = compute_science_metrics(
        BodyMetricsInput(
            weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex, impedance_ohm=impedance_ohm
        )
    )

    assert result.bmi == pytest.approx(expected["bmi"], abs=0.05)
    assert result.fat_percentage == pytest.approx(expected["fat_percentage"], abs=0.05)
    assert result.water_percentage == pytest.approx(expected["water_percentage"], abs=0.05)
    assert result.bone_mass_kg == pytest.approx(expected["bone_mass_kg"], abs=0.05)
    assert result.muscle_mass_kg == pytest.approx(expected["muscle_mass_kg"], abs=0.05)
    assert result.visceral_fat == pytest.approx(expected["visceral_fat"], abs=0.05)
    assert result.bmr_kcal == pytest.approx(expected["bmr_kcal"], abs=1.0)
    assert result.metabolic_age == pytest.approx(expected["metabolic_age"], abs=0.5)
    assert result.protein_percentage == pytest.approx(expected["protein_percentage"], abs=0.05)


@pytest.mark.parametrize(
    "weight_kg,height_cm,age,sex,impedance_ohm",
    [
        (5.0, 175.0, 30, "male", 480.0),
        (250.0, 175.0, 30, "male", 480.0),
        (70.0, 230.0, 30, "male", 480.0),
        (70.0, 175.0, 105, "male", 480.0),
        (70.0, 175.0, 30, "male", 3500.0),
        (70.0, 175.0, 30, "male", 0.0),
    ],
)
def test_out_of_range_reading_is_rejected(weight_kg, height_cm, age, sex, impedance_ohm):
    with pytest.raises(OutOfRangeReading):
        compute_science_metrics(
            BodyMetricsInput(
                weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex, impedance_ohm=impedance_ohm
            )
        )
