"""Motor de bioimpedância — modo "Xiaomi/Zepp Life".

Port direto da classe ``bodyMetrics`` de
``vendor/lolouk44_xiaomi_mi_scale/src/Xiaomi_Scale_Body_Metrics.py``
(MIT, lolouk44/xiaomi_mi_scale, commit e9db989). Fórmulas e constantes
numéricas não foram alteradas — ver THIRD_PARTY_NOTICES.md para o que mudou
na forma (classe -> funções puras) e por quê (RNF06: uma leitura fora dos
limites fisiológicos não pode derrubar o processo, então os ``exit()``
originais viraram uma exceção capturável). BMI, gordura visceral, idade
metabólica, massa óssea e massa muscular são idênticas ao modo científico —
ver ``app/engine/common.py``.
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

__all__ = ["BodyMetrics", "BodyMetricsInput", "OutOfRangeReading", "compute_xiaomi_metrics"]


def _lbm_coefficient(data: BodyMetricsInput) -> float:
    lbm = (data.height_cm * 9.058 / 100) * (data.height_cm / 100)
    lbm += data.weight_kg * 0.32 + 12.226
    lbm -= data.impedance_ohm * 0.0068
    lbm -= data.age * 0.0542
    return lbm


def _fat_percentage(data: BodyMetricsInput, lbm: float) -> float:
    if data.sex == "female" and data.age <= 49:
        const = 9.25
    elif data.sex == "female" and data.age > 49:
        const = 7.25
    else:
        const = 0.8

    if data.sex == "male" and data.weight_kg < 61:
        coefficient = 0.98
    elif data.sex == "female" and data.weight_kg > 60:
        coefficient = 0.96 * (1.03 if data.height_cm > 160 else 1.0)
    elif data.sex == "female" and data.weight_kg < 50:
        coefficient = 1.02 * (1.03 if data.height_cm > 160 else 1.0)
    else:
        coefficient = 1.0

    fat_percentage = (1.0 - (((lbm - const) * coefficient) / data.weight_kg)) * 100

    if fat_percentage > 63:
        fat_percentage = 75
    return clamp(fat_percentage, 5, 75)


def _water_percentage(fat_percentage: float) -> float:
    water_percentage = (100 - fat_percentage) * 0.7
    coefficient = 1.02 if water_percentage <= 50 else 0.98

    if water_percentage * coefficient >= 65:
        water_percentage = 75
    return clamp(water_percentage * coefficient, 35, 75)


def _bmr(data: BodyMetricsInput) -> float:
    if data.sex == "female":
        bmr = 864.6 + data.weight_kg * 10.2036
        bmr -= data.height_cm * 0.39336
        bmr -= data.age * 6.204
    else:
        bmr = 877.8 + data.weight_kg * 14.916
        bmr -= data.height_cm * 0.726
        bmr -= data.age * 8.976

    if data.sex == "female" and bmr > 2996:
        bmr = 5000
    elif data.sex == "male" and bmr > 2322:
        bmr = 5000
    return clamp(bmr, 500, 10000)


def _protein_percentage(data: BodyMetricsInput, muscle_mass: float, water_percentage: float) -> float:
    protein_percentage = (muscle_mass / data.weight_kg) * 100
    protein_percentage -= water_percentage
    return clamp(protein_percentage, 5, 32)


def compute_xiaomi_metrics(data: BodyMetricsInput) -> BodyMetrics:
    """Calcula as métricas de composição corporal no modo Xiaomi/Zepp Life.

    Levanta ``OutOfRangeReading`` se a leitura estiver fora dos limites
    fisiológicos aceitos pelo algoritmo original (RNF06) — o chamador deve
    capturar e descartar a leitura, não deixar o processo cair.
    """
    validate_reading(data)

    lbm = _lbm_coefficient(data)
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
        bmr_kcal=round(_bmr(data), 0),
        metabolic_age=round(metabolic_age(data), 0),
        protein_percentage=round(_protein_percentage(data, muscle, water_percentage), 1),
    )
