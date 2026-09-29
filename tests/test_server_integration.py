"""Testes de integração do servidor — quiosque (login + medição) e admin.

Usa o hook de teste ``app.state.on_reading`` para injetar leituras sintéticas
sem precisar de uma balança física, e ``app.state.kiosk_session`` para
adiantar o relógio da sessão sem dormir 30s de verdade nos testes.
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.ble_scanner import ScaleReading
from app.config import AppConfig
from app.server import SESSION_TIMEOUT_SECONDS, create_app


def _fake_jpeg_bytes(size: tuple[int, int] = (120, 120)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(80, 140, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


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
            files={"file": ("foto.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        )
        assert upload.status_code == 200
        photo = upload.json()
        assert photo["client_id"] == alice["id"]

        listed = client.get(f"/api/admin/clients/{alice['id']}/photos").json()
        assert len(listed) == 1

        file_response = client.get(f"/api/admin/clients/{alice['id']}/photos/{photo['id']}/file")
        assert file_response.status_code == 200
        assert file_response.headers["content-type"] == "image/jpeg"
        # o upload passa pelo Pillow agora (app/photos.py) — recodifica pra JPEG sem
        # EXIF, então os bytes não batem mais com o arquivo original, só o formato
        assert file_response.content[:2] == b"\xff\xd8"  # marcador SOI de JPEG

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


# ---------------------------------------------------------------------------
# PRD v3 — Fotometria Corporal, Etapa 1 (fundação): fase de sessão, consentimento
# de imagem e rotas seguras de captura.
# ---------------------------------------------------------------------------


def _photometry_config(**overrides) -> AppConfig:
    base = dict(
        scale_mac_address=None, host="127.0.0.1", port=8765, photometry_enabled=True, kiosk_local_only=True
    )
    base.update(overrides)
    return AppConfig(**base)


def _enable_photometry(monkeypatch, **config_overrides) -> None:
    monkeypatch.setattr("app.server.load_config", lambda: _photometry_config(**config_overrides))


def test_capturing_phase_requires_both_config_and_client_consent(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-no-consent.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=False)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            final = ws.receive_json()

        assert "capture" not in final
        # sem consentimento, a sessão vai direto pros resultados — nunca entra em "capturing"
        assert app.state.kiosk_session["current"].phase == "results"


def test_photo_prompt_appears_with_consent_and_config_enabled_for_a_never_photographed_client(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-consent.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            final = ws.receive_json()

        assert final["photo_prompt"] == {"days_since_last": None}
        session = app.state.kiosk_session["current"]
        assert session.phase == "photo_prompt"
        assert session.measurement_id == final["measurement_id"]


def test_accepting_the_photo_prompt_starts_the_capturing_phase(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-accept.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)

            answer = client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            assert answer.status_code == 200
            assert answer.json() == {"phase": "capturing"}

            started = ws.receive_json()
            assert started == {"type": "capture_started", "poses": ["front", "side", "back"], "deadline_seconds": 120}

        session = app.state.kiosk_session["current"]
        assert session.phase == "capturing"


def test_declining_the_photo_prompt_goes_straight_to_results(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-decline.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)

            answer = client.post("/api/kiosk/photo-prompt/answer", json={"accepted": False})
            assert answer.status_code == 200
            assert answer.json() == {"phase": "results"}

            declined = ws.receive_json()
            assert declined == {"type": "photo_prompt_declined"}

        assert app.state.kiosk_session["current"].phase == "results"


def test_photo_prompt_respects_the_configurable_minimum_days_since_last_photo(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    monkeypatch.setattr("app.server.PHOTOS_DIR", tmp_path / "photos")
    app = create_app(tmp_path / "photometry-min-days.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)
        app.state.db.set_photo_prompt_min_days(15)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # photo_prompt — cliente nunca fotografado, elegível
            client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            ws.receive_json()  # capture_started
            client.post(
                "/api/kiosk/capture/photo", params={"pose": "front"},
                files={"file": ("f.jpg", _fake_jpeg_bytes(), "image/jpeg")},
            )
            client.post("/api/kiosk/logout")
            ws.receive_json()  # session_ended (manual)

        # segunda sessão, logo em seguida — não passou 1 dia, muito menos 15
        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()
            app.state.on_reading(_reading(60.0))
            final = ws.receive_json()

        assert "photo_prompt" not in final
        assert app.state.kiosk_session["current"].phase == "results"


def test_photo_prompt_min_days_is_admin_configurable(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-config-days.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)

        get_default = client.get("/api/admin/settings")
        assert get_default.json() == {"photo_prompt_min_days": 15}

        updated = client.put("/api/admin/settings", json={"photo_prompt_min_days": 7})
        assert updated.status_code == 200
        assert updated.json() == {"photo_prompt_min_days": 7}
        assert client.get("/api/admin/settings").json() == {"photo_prompt_min_days": 7}


def test_photometry_disabled_by_config_never_offers_the_photo_prompt(tmp_path):
    # sem monkeypatch de load_config — usa o padrão real (photometry.enabled=False)
    app = create_app(tmp_path / "photometry-off.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            final = ws.receive_json()

        assert "photo_prompt" not in final


def test_capturing_phase_suspends_the_30s_inactivity_timeout(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-timeout-suspended.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)
            client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            ws.receive_json()  # capture_started

            session = app.state.kiosk_session["current"]
            assert session.phase == "capturing"
            session.last_activity -= SESSION_TIMEOUT_SECONDS + 1  # passou dos 30s de inatividade

            # a sessão continua viva — quem manda na fase capturing é o capture_deadline
            client.post("/api/kiosk/capture/heartbeat")
            assert app.state.kiosk_session["current"] is not None
            assert app.state.kiosk_session["current"].phase == "capturing"


def test_capturing_phase_times_out_on_its_own_deadline(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-capture-timeout.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)
            client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            ws.receive_json()  # capture_started

            session = app.state.kiosk_session["current"]
            session.capture_deadline -= 200  # já passou do prazo de 120s

            ended = ws.receive_json()
            assert ended == {"type": "session_ended", "reason": "capture_timeout"}


def test_capture_photo_upload_saves_and_replaces_same_pose(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    monkeypatch.setattr("app.server.PHOTOS_DIR", tmp_path / "photos")
    app = create_app(tmp_path / "photometry-upload.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)
            client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            ws.receive_json()  # capture_started

        upload1 = client.post(
            "/api/kiosk/capture/photo",
            params={"pose": "front"},
            files={"file": ("front.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        )
        assert upload1.status_code == 200, upload1.text
        photo1 = upload1.json()
        assert photo1["pose_type"] == "front"

        # repetir a mesma pose substitui a foto anterior, não acumula linha nova
        upload2 = client.post(
            "/api/kiosk/capture/photo",
            params={"pose": "front"},
            files={"file": ("front2.jpg", _fake_jpeg_bytes((90, 90)), "image/jpeg")},
        )
        assert upload2.status_code == 200
        photo2 = upload2.json()
        assert photo2["id"] == photo1["id"]

        listed = client.get(f"/api/admin/clients/{alice['id']}/photos")
        assert listed.status_code == 200
        assert len(listed.json()) == 1


def test_capture_photo_upload_outside_capturing_phase_is_rejected(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-wrong-phase.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=False)  # sem consentimento

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()  # session_started
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final — não entra em capturing (sem consentimento)

        response = client.post(
            "/api/kiosk/capture/photo",
            params={"pose": "front"},
            files={"file": ("front.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        )
        assert response.status_code == 409


def test_capture_photo_upload_rejects_invalid_image_content(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    monkeypatch.setattr("app.server.PHOTOS_DIR", tmp_path / "photos")
    app = create_app(tmp_path / "photometry-bad-image.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)
            client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            ws.receive_json()  # capture_started

        response = client.post(
            "/api/kiosk/capture/photo",
            params={"pose": "front"},
            files={"file": ("front.jpg", b"\xff\xd8\xff\xe0nao-e-uma-imagem-de-verdade", "image/jpeg")},
        )
        assert response.status_code == 422


def test_capture_photo_rejects_unknown_pose(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-bad-pose.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)
            client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            ws.receive_json()  # capture_started

        response = client.post(
            "/api/kiosk/capture/photo",
            params={"pose": "diagonal"},
            files={"file": ("x.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        )
        assert response.status_code == 422


def test_capture_finish_moves_phase_to_results(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    app = create_app(tmp_path / "photometry-finish.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        _create_client_via_admin(client, document="12345678909", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": "12345678909", "pin": "1234"})
            ws.receive_json()
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)
            client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            ws.receive_json()  # capture_started

        assert client.post("/api/kiosk/capture/finish").status_code == 200
        assert app.state.kiosk_session["current"].phase == "results"


def test_kiosk_get_photo_is_scoped_to_the_session_client(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    monkeypatch.setattr("app.server.PHOTOS_DIR", tmp_path / "photos")
    app = create_app(tmp_path / "photometry-photo-scope.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client, document="12345678909", photo_consent=True)
        bob = _create_client_via_admin(client, document="98765432100", full_name="Bob Lima", photo_consent=True)

        with client.websocket_connect("/ws") as ws:
            client.post("/api/kiosk/login", json={"document": alice["document"], "pin": "1234"})
            ws.receive_json()
            app.state.on_reading(_reading(60.5))
            ws.receive_json()  # final (fase photo_prompt)
            client.post("/api/kiosk/photo-prompt/answer", json={"accepted": True})
            ws.receive_json()  # capture_started

        upload = client.post(
            "/api/kiosk/capture/photo",
            params={"pose": "front"},
            files={"file": ("front.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        )
        photo_id = upload.json()["id"]

        # a foto da Alice é visível pra sessão dela...
        assert client.get(f"/api/kiosk/photos/{photo_id}").status_code == 200

        # ...mas some assim que a sessão vira a do Bob
        client.post("/api/kiosk/logout")
        client.post("/api/kiosk/login", json={"document": bob["document"], "pin": "1234"})
        assert client.get(f"/api/kiosk/photos/{photo_id}").status_code == 404


def test_kiosk_capture_routes_reject_non_local_requests_when_configured(tmp_path, monkeypatch):
    _enable_photometry(monkeypatch)
    monkeypatch.setattr("app.server._LOOPBACK_HOSTS", set())  # simula uma chamada de fora do quiosque
    app = create_app(tmp_path / "photometry-not-local.db")
    with TestClient(app) as client:
        response = client.post("/api/kiosk/capture/heartbeat")
        assert response.status_code == 403


def test_admin_sets_and_revokes_photo_consent(tmp_path):
    app = create_app(tmp_path / "photo-consent-admin.db")
    with TestClient(app) as client:
        _create_admin_and_login(client)
        alice = _create_client_via_admin(client, document="12345678909", photo_consent=False)
        assert alice["photo_consent_at"] is None

        granted = client.put(
            f"/api/admin/clients/{alice['id']}",
            json={
                "full_name": alice["full_name"], "document": alice["document"], "birthdate": alice["birthdate"],
                "sex": alice["sex"], "height_cm": alice["height_cm"], "algorithm": alice["algorithm"],
                "photo_consent": True,
            },
        )
        assert granted.status_code == 200
        assert granted.json()["photo_consent_at"] is not None

        revoked = client.put(
            f"/api/admin/clients/{alice['id']}",
            json={
                "full_name": alice["full_name"], "document": alice["document"], "birthdate": alice["birthdate"],
                "sex": alice["sex"], "height_cm": alice["height_cm"], "algorithm": alice["algorithm"],
                "photo_consent": False,
            },
        )
        assert revoked.status_code == 200
        assert revoked.json()["photo_consent_at"] is None
