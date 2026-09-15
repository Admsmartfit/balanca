"""Identificação automática de perfil por peso mais próximo (RF08).

Reimplementação enxuta da ideia de ``NearestWeightFilter`` do
``vendor/dckiller51_bodymiscale/.../profile.py`` (Apache-2.0): compara o peso
medido com o último peso conhecido de cada perfil e escolhe o mais próximo,
dentro de uma tolerância; empate ou nenhum perfil dentro da tolerância exige
confirmação manual.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .db import Profile

DEFAULT_TOLERANCE_KG = 5.0


class MatchStatus(Enum):
    MATCHED = auto()
    AMBIGUOUS = auto()
    NO_MATCH = auto()
    NO_PROFILES = auto()


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: MatchStatus
    profile: Profile | None = None
    candidates: tuple[Profile, ...] = ()


def match_profile(
    profiles: list[Profile],
    last_weight_by_profile: dict[int, float],
    measured_weight_kg: float,
    *,
    tolerance_kg: float = DEFAULT_TOLERANCE_KG,
) -> MatchResult:
    if not profiles:
        return MatchResult(status=MatchStatus.NO_PROFILES)

    if len(profiles) == 1:
        return MatchResult(status=MatchStatus.MATCHED, profile=profiles[0])

    candidates = [
        (abs(last_weight_by_profile[p.id] - measured_weight_kg), p)
        for p in profiles
        if p.id in last_weight_by_profile
    ]
    if not candidates:
        return MatchResult(status=MatchStatus.NO_MATCH, candidates=tuple(profiles))

    best_distance = min(distance for distance, _ in candidates)
    if best_distance > tolerance_kg:
        return MatchResult(status=MatchStatus.NO_MATCH, candidates=tuple(profiles))

    tied = tuple(p for distance, p in candidates if distance == best_distance)
    if len(tied) > 1:
        return MatchResult(status=MatchStatus.AMBIGUOUS, candidates=tied)

    return MatchResult(status=MatchStatus.MATCHED, profile=tied[0])
