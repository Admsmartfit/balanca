"""Testes de integração do servidor — fluxo completo de leitura BLE -> WebSocket.

Usa o hook de teste ``app.state.on_reading`` para injetar leituras sintéticas
sem precisar de uma balança física conectada.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.ble_scanner import ScaleReading
from app.server import create_app


def _reading(weight_kg: float, *, impedance_ohm: float | None = 500.0, stabilized: bool = True) -> ScaleReading:
    return ScaleReading(
        mac_address="AA:BB:CC:DD:EE:FF",
        weight_kg=weight_kg,
        unit="kg",
        impedance_ohm=impedance_ohm,
        stabilized=stabilized,
        removed=False,
    )


def test_single_profile_is_auto_matched_and_persisted(tmp_path):
    app = create_app(tmp_path / "single.db", desktop_notifications=False)
    with TestClient(app) as client:
        profile = client.post(
            "/api/profiles",
            json={"name": "Alice", "height_cm": 165, "age": 28, "sex": "female", "algorithm": "xiaomi"},
        ).json()

        with client.websocket_connect("/ws") as ws:
            app.state.on_reading(_reading(60.0, stabilized=False))
            partial = ws.receive_json()
            assert partial["type"] == "partial"

            app.state.on_reading(_reading(60.5))
            final = ws.receive_json()
            assert final["type"] == "final"
            assert final["profile"]["id"] == profile["id"]
            assert final["is_guest"] is False
            assert final["metrics"]["bmi"] is not None

        measurements = client.get(f"/api/profiles/{profile['id']}/measurements").json()
        assert len(measurements) == 1
        assert measurements[0]["weight_kg"] == 60.5


def test_weight_only_reading_is_still_persisted(tmp_path):
    """PRD seção 13, 'modo apenas peso' — sem impedância, grava o peso mesmo assim (RNF06)."""
    app = create_app(tmp_path / "weight-only.db", desktop_notifications=False)
    with TestClient(app) as client:
        profile = client.post(
            "/api/profiles",
            json={"name": "Alice", "height_cm": 165, "age": 28, "sex": "female", "algorithm": "xiaomi"},
        ).json()

        with client.websocket_connect("/ws") as ws:
            app.state.on_reading(_reading(60.5, impedance_ohm=None))
            final = ws.receive_json()
            assert final["type"] == "final"
            assert final["metrics"] is None
            assert "sem impedância" in final["warning"]

        measurements = client.get(f"/api/profiles/{profile['id']}/measurements").json()
        assert len(measurements) == 1
        assert measurements[0]["weight_kg"] == 60.5
        assert measurements[0]["bmi"] is None


def test_out_of_range_reading_is_discarded_not_persisted(tmp_path):
    app = create_app(tmp_path / "oor.db", desktop_notifications=False)
    with TestClient(app) as client:
        profile = client.post(
            "/api/profiles",
            json={"name": "Alice", "height_cm": 165, "age": 28, "sex": "female", "algorithm": "xiaomi"},
        ).json()

        with client.websocket_connect("/ws") as ws:
            app.state.on_reading(_reading(5.0))  # abaixo de 10kg — RNF06
            final = ws.receive_json()
            assert final["type"] == "final"
            assert final["metrics"] is None
            assert "fora dos limites" in final["warning"]

        measurements = client.get(f"/api/profiles/{profile['id']}/measurements").json()
        assert measurements == []


def test_no_profiles_yields_guest_reading(tmp_path):
    app = create_app(tmp_path / "guest.db", desktop_notifications=False)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            app.state.on_reading(_reading(72.0))
            final = ws.receive_json()
            assert final["type"] == "final"
            assert final["is_guest"] is True
            assert final["metrics"] is None


def test_ambiguous_match_requires_confirmation(tmp_path):
    app = create_app(tmp_path / "ambiguous.db", desktop_notifications=False)
    with TestClient(app) as client:
        alice = client.post(
            "/api/profiles",
            json={"name": "Alice", "height_cm": 165, "age": 28, "sex": "female", "algorithm": "xiaomi"},
        ).json()
        bob = client.post(
            "/api/profiles",
            json={"name": "Bob", "height_cm": 180, "age": 35, "sex": "male", "algorithm": "science"},
        ).json()

        # semeia o histórico de peso dos dois perfis diretamente (via hook de teste),
        # sem depender do próprio matching para popular os dados de setup
        app.state.db.insert_measurement(
            profile_id=alice["id"], weight_kg=70.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
        )
        app.state.db.insert_measurement(
            profile_id=bob["id"], weight_kg=74.0, unit="kg", impedance_ohm=500.0, algorithm="science", metrics=None
        )

        with client.websocket_connect("/ws") as ws:
            app.state.on_reading(_reading(72.0))  # exatamente no meio de 70 (Alice) e 74 (Bob)
            needs_confirmation = ws.receive_json()
            assert needs_confirmation["type"] == "needs_confirmation"
            candidate_ids = {c["id"] for c in needs_confirmation["candidates"]}
            assert candidate_ids == {alice["id"], bob["id"]}

            response = client.post(
                "/api/measurements/confirm",
                json={"pending_id": needs_confirmation["pending_id"], "profile_id": bob["id"]},
            )
            assert response.status_code == 200

            resolved = ws.receive_json()
            assert resolved["type"] == "final"
            assert resolved["profile"]["id"] == bob["id"]

        measurements = client.get(f"/api/profiles/{bob['id']}/measurements").json()
        # 1 medição semeada diretamente (74.0) + 1 resolvida pela confirmação (72.0)
        assert len(measurements) == 2
        assert measurements[0]["weight_kg"] == 72.0
