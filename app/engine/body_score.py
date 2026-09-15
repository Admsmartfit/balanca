"""Body Score agregado (10–100) — PRD seção 13, sugestão 1 (baixo esforço).

Port de ``vendor/dckiller51_bodymiscale/.../metrics/{body_score,scale}.py``
(Apache-2.0, dckiller51/bodymiscale, commit 684a5b9). O modo S400 (massa
muscular esquelética / dual-frequência) não foi portado — esta Fase 3 só
trabalha com massa muscular total, então o ramo SMM do original foi
removido. Fórmulas, tabelas e ordem de avaliação mantidas inalteradas,
inclusive onde ramos do ``if`` original nunca são alcançados (ver
``_body_fat_deduct_score``) — a fidelidade ao código-fonte publicado importa
mais aqui do que "corrigir" um comportamento que não foi verificado com o
mantenedor original.
"""

from __future__ import annotations

from .common import BodyMetrics, BodyMetricsInput

# Tabela de %gordura: (muito baixo, baixo, normal, alto) por faixa etária/sexo.
_FAT_SCALES: tuple[tuple[int, int, tuple[float, float, float, float], tuple[float, float, float, float]], ...] = (
    (0, 12, (12.0, 21.0, 30.0, 34.0), (7.0, 16.0, 25.0, 30.0)),
    (12, 14, (15.0, 24.0, 33.0, 37.0), (7.0, 16.0, 25.0, 30.0)),
    (14, 16, (18.0, 27.0, 36.0, 40.0), (7.0, 16.0, 25.0, 30.0)),
    (16, 18, (20.0, 28.0, 37.0, 41.0), (7.0, 16.0, 25.0, 30.0)),
    (18, 40, (21.0, 28.0, 35.0, 40.0), (11.0, 17.0, 22.0, 27.0)),
    (40, 60, (22.0, 29.0, 36.0, 41.0), (12.0, 18.0, 23.0, 28.0)),
    (60, 101, (23.0, 30.0, 37.0, 42.0), (14.0, 20.0, 25.0, 30.0)),
)

# Tabela de massa muscular: (baixo, normal) por altura mínima/sexo.
_MUSCLE_SCALES: tuple[tuple[dict[str, int], tuple[float, float], tuple[float, float]], ...] = (
    ({"male": 170, "female": 160}, (36.5, 42.6), (49.4, 59.5)),
    ({"male": 160, "female": 150}, (32.9, 37.6), (44.0, 52.5)),
    ({"male": 0, "female": 0}, (29.1, 34.8), (38.5, 46.6)),
)


def _fat_percentage_scale(age: int, sex: str) -> tuple[float, float, float, float]:
    for age_min, age_max, female, male in _FAT_SCALES:
        if age_min <= age < age_max:
            return female if sex == "female" else male
    _, _, female, male = _FAT_SCALES[-1]
    return female if sex == "female" else male


def _muscle_mass_scale(height_cm: float, sex: str) -> tuple[float, float]:
    for min_heights, female, male in _MUSCLE_SCALES:
        if height_cm >= min_heights[sex]:
            return female if sex == "female" else male
    _, female, male = _MUSCLE_SCALES[-1]
    return female if sex == "female" else male


def _malus(data: float, min_data: float, max_data: float, max_malus: float, min_malus: float) -> float:
    if (min_data - max_data) == 0:
        return 0.0
    result = ((data - max_data) / (min_data - max_data)) * (max_malus - min_malus)
    return max(0.0, result)


def _bmi_deduct_score(data: BodyMetricsInput, metrics: BodyMetrics) -> float:
    bmi_very_low, bmi_low, bmi_normal, bmi_overweight, bmi_obese = 14.0, 15.0, 18.5, 28.0, 32.0

    if data.height_cm < 90:
        return 0.0

    bmi = metrics.bmi
    fat_scale = _fat_percentage_scale(data.age, data.sex)

    if bmi <= bmi_very_low:
        return 30.0

    if (metrics.fat_percentage < fat_scale[2]) and (
        (bmi >= bmi_normal and data.age >= 18) or (bmi >= bmi_low and data.age < 18)
    ):
        return 0.0

    if bmi < bmi_low:
        return _malus(bmi, bmi_very_low, bmi_low, 30, 15) + 15.0
    if bmi < bmi_normal and data.age >= 18:
        return _malus(bmi, 15.0, 18.5, 15, 5) + 5.0

    if metrics.fat_percentage >= fat_scale[2]:
        if bmi >= bmi_obese:
            return 10.0
        if bmi > bmi_overweight:
            return _malus(bmi, 28.0, 25.0, 5, 10) + 5.0

    return 0.0


def _body_fat_deduct_score(data: BodyMetricsInput, metrics: BodyMetrics) -> float:
    scale = _fat_percentage_scale(data.age, data.sex)
    fat = metrics.fat_percentage
    best_fat_level = scale[2] - 3.0 if data.sex == "male" else scale[2] - 2.0

    if scale[0] <= fat < best_fat_level:
        return 0.0
    if fat >= scale[3]:
        return 20.0
    if fat < scale[3]:
        return _malus(fat, scale[3], scale[2], 20, 10) + 10.0
    if fat <= scale[2]:
        return _malus(fat, scale[2], best_fat_level, 3, 9) + 3.0
    if fat < scale[0]:
        return _malus(fat, 1.0, scale[0], 3, 10) + 3.0
    return 0.0


def _common_deduct_score(min_value: float, max_value: float, value: float) -> float:
    if value >= max_value:
        return 0.0
    penalty_max = 10.0
    if value < min_value:
        return penalty_max
    return _malus(value, min_value, max_value, penalty_max, 5) + 5.0


def _muscle_deduct_score(data: BodyMetricsInput, metrics: BodyMetrics) -> float:
    scale = _muscle_mass_scale(data.height_cm, data.sex)
    if metrics.muscle_mass_kg <= 0:
        return 0.0
    return _common_deduct_score(scale[0] - 5.0, scale[0], metrics.muscle_mass_kg)


def _water_deduct_score(data: BodyMetricsInput, metrics: BodyMetrics) -> float:
    normal = 55.0 if data.sex == "male" else 45.0
    return _common_deduct_score(normal - 5.0, normal, metrics.water_percentage)


def _bone_deduct_score(data: BodyMetricsInput, metrics: BodyMetrics) -> float:
    entries = (
        ((75, 2.0), (60, 1.9), (0, 1.6))
        if data.sex == "male"
        else ((60, 1.8), (45, 1.5), (0, 1.3))
    )
    expected = entries[-1][1]
    for min_weight, bone_mass in entries:
        if data.weight_kg >= min_weight:
            expected = bone_mass
            break
    return _common_deduct_score(expected - 0.3, expected, metrics.bone_mass_kg)


def _visceral_deduct_score(visceral_fat: float) -> float:
    max_data, min_data = 15.0, 10.0
    if visceral_fat < min_data:
        return 0.0
    if visceral_fat >= max_data:
        return 15.0
    return _malus(visceral_fat, max_data, min_data, max_data, min_data) + 10.0


def _basal_metabolism_deduct_score(data: BodyMetricsInput, metrics: BodyMetrics) -> float:
    coefficients = {
        "male": ((30, 21.6), (50, 20.07), (100, 19.35)),
        "female": ((30, 21.24), (50, 19.53), (100, 18.63)),
    }

    normal_bmr = 20.0
    for age_bracket, coefficient in coefficients[data.sex]:
        if data.age < age_bracket:
            normal_bmr = data.weight_kg * coefficient
            break

    bmr = metrics.bmr_kcal
    if bmr >= normal_bmr:
        return 0.0
    if bmr <= normal_bmr - 300:
        return 6.0
    return _malus(bmr, normal_bmr - 300, normal_bmr, 6, 3) + 5.0


def _protein_deduct_score(protein_percentage: float) -> float:
    if protein_percentage > 17.0:
        return 0.0
    if protein_percentage < 10.0:
        return 10.0
    if protein_percentage <= 16.0:
        return _malus(protein_percentage, 10.0, 16.0, 10, 5) + 5.0
    if protein_percentage <= 17.0:
        return _malus(protein_percentage, 16.0, 17.0, 5, 3) + 3.0
    return 0.0


def compute_body_score(data: BodyMetricsInput, metrics: BodyMetrics) -> float:
    """Agrega as métricas já calculadas em uma pontuação única de 10 a 100.

    Começa em 100 e desconta pontos por métrica fora da faixa saudável
    esperada para idade/altura/sexo. Não recalcula nada — espera as
    métricas já produzidas por ``compute_xiaomi_metrics`` ou
    ``compute_science_metrics``.
    """
    score = 100.0
    score -= _bmi_deduct_score(data, metrics)
    score -= _body_fat_deduct_score(data, metrics)
    score -= _muscle_deduct_score(data, metrics)
    score -= _water_deduct_score(data, metrics)
    score -= _visceral_deduct_score(metrics.visceral_fat)
    score -= _bone_deduct_score(data, metrics)
    score -= _basal_metabolism_deduct_score(data, metrics)
    score -= _protein_deduct_score(metrics.protein_percentage)

    if score < 10:
        return 10.0
    if score > 100:
        return 100.0
    return score
