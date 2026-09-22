"""Faixas de referência (abaixo/normal/acima) para o medidor visual do
quiosque e para o relatório em PDF.

Reaproveita as mesmas tabelas do Body Score (``body_score.py``) em vez de
inventar limiares novos — a zona "normal" mostrada aqui é a mesma que o
Body Score usa para decidir se penaliza ou não a métrica. Só quatro
métricas têm uma faixa de referência simples o bastante para um medidor de
2-3 zonas (IMC, gordura, massa muscular, gordura visceral); as demais
(água, massa óssea, proteína, BMR, idade metabólica) aparecem como número +
tendência, sem medidor — o mesmo padrão usado pelos apps de referência.
"""

from __future__ import annotations

from dataclasses import dataclass

from .body_score import _fat_percentage_scale, _muscle_mass_scale
from .common import BodyMetricsInput

# IMC: padrão OMS (peso normal = 18.5-25 kg/m²), independente de idade/sexo.
BMI_LOW, BMI_HIGH = 18.5, 25.0

# Gordura visceral: classificação Zepp Life — 1-9 normal, 10+ acima do ideal.
# Exposto como limiar único porque o medidor do PRD só tem 2 zonas aqui.
VISCERAL_FAT_THRESHOLD = 10.0


@dataclass(frozen=True, slots=True)
class Range:
    low: float | None  # None = zona "normal" não tem piso (começa em zero)
    high: float | None  # None = zona "normal" não tem teto


def bmi_range(_: BodyMetricsInput) -> Range:
    return Range(BMI_LOW, BMI_HIGH)


def fat_percentage_range(data: BodyMetricsInput) -> Range:
    scale = _fat_percentage_scale(data.age, data.sex)
    return Range(scale[1], scale[2])


def muscle_mass_range(data: BodyMetricsInput) -> Range:
    low, high = _muscle_mass_scale(data.height_cm, data.sex)
    return Range(low, high)


def visceral_fat_range(_: BodyMetricsInput) -> Range:
    return Range(None, VISCERAL_FAT_THRESHOLD)


RANGE_PROVIDERS = {
    "bmi": bmi_range,
    "fat_percentage": fat_percentage_range,
    "muscle_mass_kg": muscle_mass_range,
    "visceral_fat": visceral_fat_range,
}


def reference_ranges_for(data: BodyMetricsInput) -> dict[str, Range]:
    """Retorna a faixa de referência de cada métrica que tem uma (RF03/PDF)."""
    return {metric: provider(data) for metric, provider in RANGE_PROVIDERS.items()}
