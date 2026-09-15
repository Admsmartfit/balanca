"""Motor de bioimpedância — modo "Científico" (RF06).

Port das fórmulas mono-frequência de
``vendor/dckiller51_bodymiscale/custom_components/bodymiscale/`` (Apache-2.0,
dckiller51/bodymiscale, commit 684a5b9): ``metrics/impedance.py``
(``get_lbm``, ``get_fat_percentage``, ``get_water_percentage``,
``get_protein_percentage``, caminho não-dual) e ``util.py``
(``get_bmr_schofield``). O modo S400 (dual-frequência) do repositório de
origem não foi portado — fica para a Fase 3 (PRD seção 13). BMI, gordura
visceral, idade metabólica, massa óssea e massa muscular são idênticas ao
modo Xiaomi — ver ``app/engine/common.py``.
"""

from __future__ import annotations

from .common import (
    BodyMetrics,
    BodyMetricsInput,
    OutOfRangeReading,
    bmi,
    bone_mass,
    clamp,
    metabolic_age,
    muscle_mass,
    validate_reading,
    visceral_fat,
)

__all__ = ["BodyMetrics", "BodyMetricsInput", "OutOfRangeReading", "compute_science_metrics"]

# Schofield (WHO) — (coeficiente angular, constante) por faixa etária.
# Faixas: 0-3, 3-10, 10-18, 18-30, 30-60, 60+.
# Fonte: vendor/dckiller51_bodymiscale/.../util.py::get_bmr_schofield
_SCHOFIELD_MALE = (
    (59.512, -30.4),
    (22.706, 504.3),
    (17.686, 658.2),
    (15.057, 692.2),
    (11.472, 873.1),
    (11.711, 587.7),
)
_SCHOFIELD_FEMALE = (
    (58.317, -31.1),
    (20.315, 485.9),
    (13.384, 692.6),
    (14.818, 486.6),
    (8.126, 845.6),
    (9.082, 658.5),
)


def _lbm(data: BodyMetricsInput) -> float:
    h, w, a, z = data.height_cm, data.weight_kg, data.age, data.impedance_ohm
    lbm = (h * 9.058 / 100.0) * (h / 100.0) + w * 0.32 + 12.226 - z * 0.0068 - a * 0.0542

    # Correção de dimorfismo sexual: a regressão de base não tem termo de
    # sexo e superestima a LBM feminina em ~16% (bodymiscale impedance.py).
    if data.sex == "female":
        lbm *= 0.84

    return min(lbm, w * 0.98)


def _fat_percentage(data: BodyMetricsInput, lbm: float) -> float:
    fat_percentage = (data.weight_kg - lbm) / data.weight_kg * 100.0
    min_fat = 10.0 if data.sex == "female" else 5.0
    return clamp(fat_percentage, min_fat, 75.0)


def _water_percentage(fat_percentage: float) -> float:
    water_percentage = (100.0 - fat_percentage) * 0.73
    return clamp(water_percentage, 35.0, 73.0)


def _bmr_schofield(data: BodyMetricsInput) -> float:
    coeffs = _SCHOFIELD_FEMALE if data.sex == "female" else _SCHOFIELD_MALE
    age = data.age
    if age < 3:
        slope, constant = coeffs[0]
    elif age < 10:
        slope, constant = coeffs[1]
    elif age < 18:
        slope, constant = coeffs[2]
    elif age < 30:
        slope, constant = coeffs[3]
    elif age < 60:
        slope, constant = coeffs[4]
    else:
        slope, constant = coeffs[5]

    bmr = slope * data.weight_kg + constant
    return clamp(bmr, 500, 5000)


def _protein_percentage(data: BodyMetricsInput, lbm: float) -> float:
    protein_percentage = lbm * 0.195 / data.weight_kg * 100.0
    return clamp(protein_percentage, 5, 32)


def compute_science_metrics(data: BodyMetricsInput) -> BodyMetrics:
    """Calcula as métricas de composição corporal no modo científico.

    Levanta ``OutOfRangeReading`` se a leitura estiver fora dos limites
    fisiológicos aceitos (RNF06) — o chamador deve capturar e descartar a
    leitura, não deixar o processo cair.
    """
    validate_reading(data)

    lbm = _lbm(data)
    fat_percentage = _fat_percentage(data, lbm)
    water_percentage = _water_percentage(fat_percentage)
    bone = bone_mass(data, lbm)
    muscle = muscle_mass(data, fat_percentage, bone)

    return BodyMetrics(
        bmi=round(bmi(data), 1),
        fat_percentage=round(fat_percentage, 1),
        water_percentage=round(water_percentage, 1),
        bone_mass_kg=round(bone, 2),
        muscle_mass_kg=round(muscle, 1),
        visceral_fat=round(visceral_fat(data), 1),
        bmr_kcal=round(_bmr_schofield(data), 0),
        metabolic_age=round(metabolic_age(data), 0),
        protein_percentage=round(_protein_percentage(data, lbm), 1),
    )
