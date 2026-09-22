"""Testes do motor de sugestão por peso (RF04)."""

from app.db import Client
from app.matching import suggest_clients_by_weight


def _client(id_: int, name: str) -> Client:
    return Client(
        id=id_, full_name=name, document=f"1111111111{id_}", birthdate="1990-01-01",
        sex="male", height_cm=175, algorithm="xiaomi",
    )


def test_suggests_closest_client_within_tolerance():
    alice, bob = _client(1, "Alice"), _client(2, "Bob")
    last_weights = {1: 70.0, 2: 90.0}
    suggestions = suggest_clients_by_weight([alice, bob], last_weights, measured_weight_kg=71.0)
    assert suggestions == [alice]


def test_suggests_up_to_three_ordered_by_distance():
    a, b, c, d = _client(1, "A"), _client(2, "B"), _client(3, "C"), _client(4, "D")
    # distâncias até 70.0: A=0, D=0.5, C=1.5, B=1.8 — B fica de fora por causa do limit=3
    last_weights = {1: 70.0, 2: 71.8, 3: 68.5, 4: 69.5}
    suggestions = suggest_clients_by_weight(
        [a, b, c, d], last_weights, measured_weight_kg=70.0, tolerance_kg=2.0, limit=3
    )
    assert [c.full_name for c in suggestions] == ["A", "D", "C"]


def test_excludes_clients_outside_tolerance():
    alice, bob = _client(1, "Alice"), _client(2, "Bob")
    last_weights = {1: 70.0, 2: 90.0}
    suggestions = suggest_clients_by_weight([alice, bob], last_weights, measured_weight_kg=71.0, tolerance_kg=2.0)
    assert bob not in suggestions


def test_excludes_clients_without_weight_history():
    alice, bob = _client(1, "Alice"), _client(2, "Bob")
    suggestions = suggest_clients_by_weight([alice, bob], {1: 70.0}, measured_weight_kg=70.0)
    assert suggestions == [alice]


def test_no_clients_returns_empty_list():
    assert suggest_clients_by_weight([], {}, measured_weight_kg=70.0) == []


def test_no_match_within_tolerance_returns_empty_list():
    alice = _client(1, "Alice")
    suggestions = suggest_clients_by_weight([alice], {1: 70.0}, measured_weight_kg=90.0, tolerance_kg=2.0)
    assert suggestions == []
