"""Tipos e fórmulas compartilhadas entre os modos "Xiaomi" e "Científico" (RF06).

BMI, gordura visceral, idade metabólica, massa óssea e massa muscular usam a
mesma fórmula nos dois modos — confirmado comparando
``vendor/lolouk44_xiaomi_mi_scale/src/Xiaomi_Scale_Body_Metrics.py`` (modo
Xiaomi) com ``vendor/dckiller51_bodymiscale/.../metrics/{impedance,weight}.py``
(modo científico, onde essas mesmas fórmulas aparecem documentadas como
"common to all 3 modes"). Isolar essas cinco funções aqui evita duas cópias
divergentes do mesmo cálculo.
"""

from __future__ import annotations

from dataclasses import dataclass


class OutOfRangeReading(ValueError):
    """Peso, altura, idade ou impedância fora dos limites fisiológicos (RNF06)."""


@dataclass(frozen=True, slots=True)
class BodyMetricsInput:
    weight_kg: float
    height_cm: float
    age: int
    sex: str  # "male" | "female"
    impedance_ohm: float


@dataclass(frozen=True, slots=True)
class BodyMetrics:
    bmi: float
    fat_percentage: float
    water_percentage: float
    bone_mass_kg: float
    muscle_mass_kg: float
    visceral_fat: float
    bmr_kcal: float
    metabolic_age: float
    protein_percentage: float


def clamp(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def validate_reading(data: BodyMetricsInput) -> None:
    if data.height_cm > 220:
        raise OutOfRangeReading(f"height {data.height_cm}cm is over 220cm")
    if data.weight_kg < 10 or data.weight_kg > 200:
        raise OutOfRangeReading(f"weight {data.weight_kg}kg is out of [10, 200]")
    if data.age > 99:
        raise OutOfRangeReading(f"age {data.age} is over 99 years")
    if data.impedance_ohm <= 0 or data.impedance_ohm > 3000:
        raise OutOfRangeReading(f"impedance {data.impedance_ohm} ohm is out of (0, 3000]")


def bmi(data: BodyMetricsInput) -> float:
    return clamp(data.weight_kg / ((data.height_cm / 100) ** 2), 10, 90)


def visceral_fat(data: BodyMetricsInput) -> float:
    h, w, a = data.height_cm, data.weight_kg, data.age

    if data.sex == "female":
        if w > (13 - (h * 0.5)) * -1:
            subsubcalc = ((h * 1.45) + (h * 0.1158) * h) - 120
            subcalc = w * 500 / subsubcalc
            vfal = (subcalc - 6) + (a * 0.07)
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

    return clamp(vfal, 1, 50)


def metabolic_age(data: BodyMetricsInput) -> float:
    h, w, a, z = data.height_cm, data.weight_kg, data.age, data.impedance_ohm
    if data.sex == "female":
        value = (h * -1.1165) + (w * 1.5784) + (a * 0.4615) + (z * 0.0415) + 83.2548
    else:
        value = (h * -0.7471) + (w * 0.9161) + (a * 0.4184) + (z * 0.0517) + 54.2267
    return clamp(value, 15, 80)


def bone_mass(data: BodyMetricsInput, lbm: float) -> float:
    base = 0.245691014 if data.sex == "female" else 0.18016894
    mass = (base - (lbm * 0.05158)) * -1

    mass = mass + 0.1 if mass > 2.2 else mass - 0.1

    if data.sex == "female" and mass > 5.1:
        mass = 8
    elif data.sex == "male" and mass > 5.2:
        mass = 8
    return clamp(mass, 0.5, 8)


def muscle_mass(data: BodyMetricsInput, fat_percentage: float, bone_mass_kg: float) -> float:
    mass = data.weight_kg - (fat_percentage * 0.01 * data.weight_kg) - bone_mass_kg

    if data.sex == "female" and mass >= 84:
        mass = 120
    elif data.sex == "male" and mass >= 93.5:
        mass = 120

    return clamp(mass, 10, 120)
