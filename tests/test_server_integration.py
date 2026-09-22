"""Testes de integração do servidor — quiosque (login + medição) e admin.

Usa o hook de teste ``app.state.on_reading`` para injetar leituras sintéticas
sem precisar de uma balança física, e ``app.state.kiosk_session`` para
adiantar o relógio da sessão sem dormir 30s de verdade nos testes.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.ble_scanner import ScaleReading
from app.server import SESSION_TIMEOUT_SECONDS, create_app


def _reading(weight_kg: float, *, impedance_ohm: float | None = 500.0, stabilized: bool = True) -> ScaleReading:
    return ScaleReading(
        mac_address="AA:BB:CC:DD:EE:FF",
        weight_kg=weight_kg,
        unit="kg",
        impedance_ohm=impedance_ohm,
        stabilized=stabilized,
        removed=False,
    )


def _create_admin_and_login(client: TestClient) -> None:
    client.app.state.db.create_admin(email="admin@exemplo.com", password="senhasegura123")
    response = client.post("/api/admin/login", json={"email": "admin@exemplo.com", "password": "senhasegura123"})
    assert response.status_code == 200


def _create_client_via_admin(client: TestClient, **overrides) -> dict:
    body = {
        "full_name": "Alice Souza",
        "document": "12345678909",
        "birthdate": "1998-04-12",
        "sex": "female",
        "height_cm": 165,
        "algorithm": "xiaomi",
        "pin": "1234",
        "accepted_terms": True,
    }
    body.update(overrides)
    response = client.post("/api/admin/clients", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Quiosque: login + medição
# ---------------------------------------------------------------------------


def test_login_by_document_and_pin_starts_session_and_weighs(tmp_path):
    app = create_app(tmp_path / "kiosk.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client)

        with client.websocket_connect("/ws") as ws:
            login = client.post("/api/kiosk/login", json={"document": "123.456.789-09", "pin": "1234"})
            assert login.status_code == 200
            started = ws.receive_json()
            assert started["type"] == "session_started"
            assert started["client"]["id"] == alice["id"]

            app.state.on_reading(_reading(60.5))
            final = ws.receive_json()
            assert final["type"] == "final"
            assert final["client"]["id"] == alice["id"]
            assert final["metrics"]["bmi"] is not None
            assert final["measurement_id"] is not None
            assert final["ranges"]["bmi"] == {"low": 18.5, "high": 25.0}
            assert "muscle_mass_kg" in final["ranges"]
            assert "water_percentage" not in final["ranges"]  # sem faixa de referência definida

        measurements = client.get(f"/api/admin/clients/{alice['id']}/measurements").json()
        assert len(measurements) == 1
        assert measurements[0]["weight_kg"] == 60.5


def test_login_with_wrong_pin_is_rejected(tmp_path):
    app = create_app(tmp_path / "wrongpin.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client)

        response = client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "0000"})
        assert response.status_code == 401


def test_login_with_unknown_document_is_rejected(tmp_path):
    app = create_app(tmp_path / "unknown.db")
    with TestClient(app) as client:
        response = client.post("/api/kiosk/login", json={"document": "00000000000", "pin": "1234"})
        assert response.status_code == 401


def test_idle_weight_suggests_matching_clients(tmp_path):
    app = create_app(tmp_path / "suggest.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client, document="12345678909")
        client.app.state.db.insert_measurement(
            client_id=alice["id"], weight_kg=60.0, unit="kg", impedance_ohm=500.0, algorithm="xiaomi", metrics=None
        )

        with client.websocket_connect("/ws") as ws:
            app.state.on_reading(_reading(60.5))
            message = ws.receive_json()
            assert message["type"] == "idle_weight"
            assert [c["id"] for c in message["suggestions"]] == [alice["id"]]

            login = client.post("/api/kiosk/login", json={"client_id": alice["id"], "pin": "1234"})
            assert login.status_code == 200
            started = ws.receive_json()
            assert started["type"] == "session_started"


def test_logout_ends_session(tmp_path):
    app = create_app(tmp_path / "logout.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909")

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started

            response = client.post("/api/kiosk/logout")
            assert response.status_code == 200
            ended = ws.receive_json()
            assert ended == {"type": "session_ended", "reason": "manual"}

        state = client.get("/api/kiosk/state").json()
        assert state["status"] == "idle"


def test_session_times_out_after_inactivity(tmp_path):
    app = create_app(tmp_path / "timeout.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909")

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started

            # adianta o relógio da sessão em vez de dormir 30s de verdade
            session = app.state.kiosk_session["current"]
            session.last_activity -= SESSION_TIMEOUT_SECONDS + 1

            ended = ws.receive_json()
            assert ended == {"type": "session_ended", "reason": "timeout"}


def test_weight_only_reading_is_discarded_not_persisted(tmp_path):
    """Sem impedância válida não há composição corporal pra registrar — a leitura só
    aparece na tela do quiosque (peso + aviso), sem entrar no histórico do cliente."""
    app = create_app(tmp_path / "weightonly.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client, document="12345678909")

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started

            app.state.on_reading(_reading(60.5, impedance_ohm=None))
            final = ws.receive_json()
            assert final["metrics"] is None
            assert final["measurement_id"] is None
            assert "sem impedância" in final["warning"]

        measurements = client.get(f"/api/admin/clients/{alice['id']}/measurements").json()
        assert measurements == []


def test_out_of_range_reading_is_discarded_not_persisted(tmp_path):
    app = create_app(tmp_path / "oor.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client, document="12345678909")

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started

            app.state.on_reading(_reading(5.0))  # abaixo de 10kg — RNF06
            final = ws.receive_json()
            assert final["metrics"] is None
            assert "fora dos limites" in final["warning"]

        assert client.get(f"/api/admin/clients/{alice['id']}/measurements").json() == []


# ---------------------------------------------------------------------------
# Administração
# ---------------------------------------------------------------------------


def test_admin_endpoints_require_authentication(tmp_path):
    app = create_app(tmp_path / "noauth.db")
    with TestClient(app) as client:
        assert client.get("/api/admin/clients").status_code == 401
        assert client.get("/api/admin/me").status_code == 401


def test_admin_login_wrong_password_rejected(tmp_path):
    app = create_app(tmp_path / "wrongpw.db")
    with TestClient(app) as client:
        client.app.state.db.create_admin(email="admin@exemplo.com", password="senhasegura123")
        response = client.post("/api/admin/login", json={"email": "admin@exemplo.com", "password": "errada"})
        assert response.status_code == 401


def test_admin_full_client_crud_flow(tmp_path):
    app = create_app(tmp_path / "crud.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client)

        listed = client.get("/api/admin/clients").json()
        assert len(listed) == 1

        updated = client.put(
            f"/api/admin/clients/{alice['id']}",
            json={
                "full_name": "Alice S. Souza",
                "document": alice["document"],
                "birthdate": alice["birthdate"],
                "sex": alice["sex"],
                "height_cm": 170,
                "algorithm": "science",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["height_cm"] == 170

        reset = client.post(f"/api/admin/clients/{alice['id']}/reset-pin", json={"new_pin": "9999"})
        assert reset.status_code == 200
        assert client.post("/api/kiosk/login", json={"client_id": alice["id"], "pin": "1234"}).status_code == 401
        assert client.post("/api/kiosk/login", json={"client_id": alice["id"], "pin": "9999"}).status_code == 200

        deleted = client.delete(f"/api/admin/clients/{alice['id']}")
        assert deleted.status_code == 200
        assert client.get("/api/admin/clients").json() == []


def test_admin_logout_invalidates_session(tmp_path):
    app = create_app(tmp_path / "adminlogout.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        assert client.get("/api/admin/me").status_code == 200

        client.post("/api/admin/logout")
        assert client.get("/api/admin/me").status_code == 401


# ---------------------------------------------------------------------------
# Resultado moderno: histórico do quiosque, PDF automático, fotos
# ---------------------------------------------------------------------------


def test_kiosk_history_returns_authenticated_clients_measurements(tmp_path, monkeypatch):
    app = create_app(tmp_path / "history.db")
    monkeypatch.setattr("app.report.REPORTS_DIR", tmp_path / "reports")
    with TestClient(app) as client:
        assert client.get("/api/kiosk/history").json() == []  # sem sessão ativa

        _create_admin_and_login(client)
        alice = _create_client_via_admin(client)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started

            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final
            app.state.on_reading(_reading(61.0))
            ws.receive_json()  # final

        history = client.get("/api/kiosk/history").json()
        assert [m["weight_kg"] for m in history] == [61.0, 60.5]  # mais recente primeiro


def test_measurement_generates_downloadable_pdf_report(tmp_path, monkeypatch):
    app = create_app(tmp_path / "pdf.db")
    monkeypatch.setattr("app.report.REPORTS_DIR", tmp_path / "reports")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            final = ws.receive_json()

        measurement_id = final["measurement_id"]
        response = client.get(f"/api/admin/clients/{alice['id']}/measurements/{measurement_id}/report")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content[:4] == b"%PDF"


def test_photo_upload_list_file_and_delete(tmp_path, monkeypatch):
    app = create_app(tmp_path / "photos.db")
    monkeypatch.setattr("app.server.PHOTOS_DIR", tmp_path / "photos")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client)

        upload = client.post(
            f"/api/admin/clients/{alice['id']}/photos",
            files={"file": ("foto.jpg", b"\xff\xd8\xff\xe0fakejpegbytes", "image/jpeg")},
        )
        assert upload.status_code == 200
        photo = upload.json()
        assert photo["client_id"] == alice["id"]

        listed = client.get(f"/api/admin/clients/{alice['id']}/photos").json()
        assert len(listed) == 1

        file_response = client.get(f"/api/admin/clients/{alice['id']}/photos/{photo['id']}/file")
        assert file_response.status_code == 200
        assert file_response.headers["content-type"] == "image/jpeg"
        assert file_response.content == b"\xff\xd8\xff\xe0fakejpegbytes"

        deleted = client.delete(f"/api/admin/clients/{alice['id']}/photos/{photo['id']}")
        assert deleted.status_code == 200
        assert client.get(f"/api/admin/clients/{alice['id']}/photos").json() == []


def test_photo_upload_rejects_non_image_files(tmp_path, monkeypatch):
    app = create_app(tmp_path / "photos-reject.db")
    monkeypatch.setattr("app.server.PHOTOS_DIR", tmp_path / "photos")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client)

        response = client.post(
            f"/api/admin/clients/{alice['id']}/photos",
            files={"file": ("nota.txt", b"nao e uma imagem", "text/plain")},
        )
        assert response.status_code == 422


def test_photo_endpoints_require_admin_auth(tmp_path):
    app = create_app(tmp_path / "photos-auth.db")
    with TestClient(app) as client:
        assert client.get("/api/admin/clients/1/photos").status_code == 401
