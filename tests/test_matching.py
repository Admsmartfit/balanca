"""Testes da identificação automática de perfil por peso (RF08)."""

from app.db import Profile
from app.matching import MatchStatus, match_profile


def _profile(id_: int, name: str) -> Profile:
    return Profile(id=id_, name=name, height_cm=170.0, age=30, sex="male", algorithm="xiaomi")


def test_single_profile_always_matches_without_weight_history():
    alice = _profile(1, "alice")
    result = match_profile([alice], {}, measured_weight_kg=999.0)
    assert result.status is MatchStatus.MATCHED
    assert result.profile == alice


def test_no_profiles_returns_no_profiles():
    result = match_profile([], {}, measured_weight_kg=70.0)
    assert result.status is MatchStatus.NO_PROFILES


def test_matches_the_closest_profile_within_tolerance():
    alice, bob = _profile(1, "alice"), _profile(2, "bob")
    last_weights = {1: 60.0, 2: 85.0}
    result = match_profile([alice, bob], last_weights, measured_weight_kg=61.5)
    assert result.status is MatchStatus.MATCHED
    assert result.profile == alice


def test_ambiguous_when_two_profiles_tie():
    alice, bob = _profile(1, "alice"), _profile(2, "bob")
    last_weights = {1: 70.0, 2: 74.0}
    result = match_profile([alice, bob], last_weights, measured_weight_kg=72.0)
    assert result.status is MatchStatus.AMBIGUOUS
    assert set(result.candidates) == {alice, bob}


def test_no_match_when_outside_tolerance():
    alice, bob = _profile(1, "alice"), _profile(2, "bob")
    last_weights = {1: 60.0, 2: 85.0}
    result = match_profile([alice, bob], last_weights, measured_weight_kg=72.5, tolerance_kg=5.0)
    assert result.status is MatchStatus.NO_MATCH


def test_no_match_when_no_profile_has_weight_history():
    alice, bob = _profile(1, "alice"), _profile(2, "bob")
    result = match_profile([alice, bob], {}, measured_weight_kg=70.0)
    assert result.status is MatchStatus.NO_MATCH
    assert set(result.candidates) == {alice, bob}


def test_profile_without_history_is_excluded_from_candidates():
    alice, bob = _profile(1, "alice"), _profile(2, "bob")
    # só bob tem histórico — alice não pode ser candidata, mesmo estando mais perto
    last_weights = {2: 90.0}
    result = match_profile([alice, bob], last_weights, measured_weight_kg=70.0, tolerance_kg=50.0)
    assert result.status is MatchStatus.MATCHED
    assert result.profile == bob
