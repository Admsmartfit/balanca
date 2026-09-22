"""FastAPI + WebSocket — quiosque de login por CPF/telefone + PIN e painel
administrativo, conforme o PRD de cadastro e autenticação.

Duas superfícies servidas pelo mesmo processo:

- **Quiosque** (`/`, teclado numérico físico USB): motor de sugestão por
  peso (RF04) enquanto ninguém está autenticado, login por documento+PIN ou
  por sugestão+PIN (RF01/RF03), medição vinculada à sessão autenticada,
  timeout de 30s sem toque nem variação de peso (RF06). O resultado inclui
  faixas de referência (abaixo/normal/acima) e o histórico recente do
  cliente (`GET /api/kiosk/history`) para o medidor visual e os
  mini-gráficos de tendência do painel de resultado.
- **Painel administrativo** (`/admin`, mouse+teclado): login por
  e-mail+senha (RF07 — RBAC), CRUD de clientes, reset manual de PIN
  (substitui a recuperação por SMS/WhatsApp do PRD — ver
  THIRD_PARTY_NOTICES.md), histórico e exportação por cliente, download do
  relatório em PDF de cada medição, e fotos de evolução por cliente.

Cada medição persistida também gera um PDF automaticamente em segundo
plano (`app/report.py`, salvo em `data/reports/`) — o envio desse PDF
(e-mail, WhatsApp etc.) é trabalho futuro, fora do escopo atual.

O scanner BLE roda na mesma `asyncio` loop do servidor, publica cada leitura
em uma fila; uma task separada consome a fila e decide, com base em existir
ou não uma sessão de quiosque autenticada, se a leitura alimenta o motor de
sugestão ou uma medição de verdade.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .ble_scanner import MiScaleScanner, ScaleReading
from .config import ROOT_DIR, WEB_DIR, load_config
from .db import DB_PATH, Client, Database, InvalidClient
from .engine import BodyMetricsInput, OutOfRangeReading, Range, compute_body_score, compute_metrics, reference_ranges_for
from .matching import suggest_clients_by_weight
from .report import generate_and_save_report, generate_measurement_report, report_path_for
from .security import ADMIN_SESSION_COOKIE, ADMIN_SESSION_TTL_SECONDS, AdminSessionStore, verify_password

logger = logging.getLogger(__name__)

SESSION_TIMEOUT_SECONDS = 30
WEIGHT_CHANGE_EPSILON_KG = 0.2
IDLE_SUGGESTION_MIN_KG = 10.0
IDLE_SUGGESTION_MAX_KG = 200.0
PHOTOS_DIR = ROOT_DIR / "data" / "photos"
MAX_PHOTO_BYTES = 8 * 1024 * 1024


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for connection in self._connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)


@dataclass(slots=True)
class KioskSession:
    client_id: int
    authenticated_at: float
    last_activity: float
    last_weight_seen: float | None = None


# ---------------------------------------------------------------------------
# Modelos de request
# ---------------------------------------------------------------------------


class KioskLoginIn(BaseModel):
    document: str | None = None
    client_id: int | None = None
    pin: str

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "KioskLoginIn":
        if (self.document is None) == (self.client_id is None):
            raise ValueError("informe exatamente um entre document e client_id")
        return self


class ClientIn(BaseModel):
    full_name: str
    document: str
    birthdate: str  # YYYY-MM-DD
    sex: str
    height_cm: float = Field(ge=100, le=220)
    algorithm: str = "xiaomi"


class ClientCreateIn(ClientIn):
    pin: str
    accepted_terms: bool = False


class PinResetIn(BaseModel):
    new_pin: str


class AdminLoginIn(BaseModel):
    email: str
    password: str


def _metrics_to_dict(metrics, body_score: float) -> dict:
    return {
        "bmi": metrics.bmi,
        "fat_percentage": metrics.fat_percentage,
        "water_percentage": metrics.water_percentage,
        "bone_mass_kg": metrics.bone_mass_kg,
        "muscle_mass_kg": metrics.muscle_mass_kg,
        "visceral_fat": metrics.visceral_fat,
        "bmr_kcal": metrics.bmr_kcal,
        "metabolic_age": metrics.metabolic_age,
        "protein_percentage": metrics.protein_percentage,
        "body_score": body_score,
    }


def _ranges_to_dict(ranges: dict[str, Range]) -> dict:
    return {metric: {"low": r.low, "high": r.high} for metric, r in ranges.items()}


def _compute_for_client(
    client: Client, reading: ScaleReading
) -> tuple[dict | None, dict | None, str | None, bool]:
    """Retorna (métricas ou None, faixas de referência ou None, aviso ou None, persistir?).

    Sem impedância válida não há composição corporal pra calcular nem pra
    mostrar no histórico/relatório — a leitura só de peso é descartada, não
    persistida (mesmo tratamento de uma leitura fora dos limites
    fisiológicos, RNF06). O quiosque ainda mostra o peso e o aviso na tela,
    só não grava uma linha vazia no histórico do cliente.
    """
    if reading.impedance_ohm is None:
        return None, None, "sem impedância válida — só o peso foi registrado", False

    body_metrics_input = BodyMetricsInput(
        weight_kg=reading.weight_kg,
        height_cm=client.height_cm,
        age=client.age,
        sex=client.sex,
        impedance_ohm=reading.impedance_ohm,
    )
    try:
        metrics = compute_metrics(client.algorithm, body_metrics_input)
    except OutOfRangeReading as exc:
        logger.warning("leitura descartada (RNF06): %s", exc)
        return None, None, f"leitura fora dos limites fisiológicos: {exc}", False

    body_score = compute_body_score(body_metrics_input, metrics)
    ranges = _ranges_to_dict(reference_ranges_for(body_metrics_input))
    return _metrics_to_dict(metrics, body_score), ranges, None, True


def create_app(db_path: Path = DB_PATH) -> FastAPI:
    config = load_config()
    db = Database(db_path)
    manager = ConnectionManager()
    admin_sessions = AdminSessionStore()
    reading_queue: asyncio.Queue[ScaleReading] = asyncio.Queue()
    last_seen: dict[str, tuple[float, float | None, bool]] = {}
    loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
    kiosk_session: dict[str, KioskSession | None] = {"current": None}

    def on_reading(reading: ScaleReading) -> None:
        # bleak chama isso na loop do app; testes/hooks externos podem chamar de outra
        # thread (ex.: TestClient) — call_soon_threadsafe cobre os dois casos.
        loop = loop_holder.get("loop")
        if loop is not None:
            loop.call_soon_threadsafe(reading_queue.put_nowait, reading)
        else:
            reading_queue.put_nowait(reading)

    scanner = MiScaleScanner(config.scale_mac_address, on_reading)

    def touch_session() -> None:
        session = kiosk_session["current"]
        if session is not None:
            session.last_activity = time.monotonic()

    async def end_session(reason: str) -> None:
        if kiosk_session["current"] is None:
            return
        kiosk_session["current"] = None
        await manager.broadcast({"type": "session_ended", "reason": reason})

    async def start_session(client: Client) -> None:
        kiosk_session["current"] = KioskSession(
            client_id=client.id, authenticated_at=time.monotonic(), last_activity=time.monotonic()
        )
        await manager.broadcast({"type": "session_started", "client": client.as_dict()})

    async def handle_idle_reading(reading: ScaleReading) -> None:
        if not (IDLE_SUGGESTION_MIN_KG <= reading.weight_kg <= IDLE_SUGGESTION_MAX_KG):
            return
        suggestions = suggest_clients_by_weight(db.list_clients(), db.last_weight_by_client(), reading.weight_kg)
        await manager.broadcast(
            {
                "type": "idle_weight",
                "weight_kg": reading.weight_kg,
                "unit": reading.unit,
                "suggestions": [c.as_public_dict() for c in suggestions],
            }
        )

    async def handle_authenticated_reading(session: KioskSession, reading: ScaleReading) -> None:
        if session.last_weight_seen is None or abs(reading.weight_kg - session.last_weight_seen) > (
            WEIGHT_CHANGE_EPSILON_KG
        ):
            session.last_weight_seen = reading.weight_kg
            session.last_activity = time.monotonic()

        if not reading.stabilized or reading.removed:
            await manager.broadcast(
                {"type": "partial", "weight_kg": reading.weight_kg, "unit": reading.unit}
            )
            return

        client = db.get_client(session.client_id)
        if client is None:  # cliente excluído pelo admin no meio da sessão
            await end_session("client_removed")
            return

        metrics, ranges, warning, persist = _compute_for_client(client, reading)
        measurement_id = None
        if persist:
            measurement_id = db.insert_measurement(
                client_id=client.id,
                weight_kg=reading.weight_kg,
                unit=reading.unit,
                impedance_ohm=reading.impedance_ohm,
                algorithm=client.algorithm,
                metrics=metrics,
            )
            if metrics is not None:
                asyncio.create_task(_generate_report(client.id, measurement_id))
        await manager.broadcast(
            {
                "type": "final",
                "weight_kg": reading.weight_kg,
                "unit": reading.unit,
                "client": client.as_dict(),
                "algorithm": client.algorithm,
                "metrics": metrics,
                "ranges": ranges,
                "measurement_id": measurement_id,
                "warning": warning,
            }
        )

    async def _generate_report(client_id: int, measurement_id: int) -> None:
        """Gera o PDF do resultado em segundo plano — nunca bloqueia nem derruba a leitura da balança."""
        try:
            client = db.get_client(client_id)
            measurement = db.get_measurement(measurement_id)
            if client is None or measurement is None:
                return
            await asyncio.to_thread(generate_and_save_report, client, measurement)
        except Exception:
            logger.exception("falha ao gerar o PDF da medição %s", measurement_id)

    async def consume_readings() -> None:
        while True:
            reading = await reading_queue.get()
            dedupe_key = (reading.weight_kg, reading.impedance_ohm, reading.stabilized)
            if last_seen.get(reading.mac_address) == dedupe_key:
                continue
            last_seen[reading.mac_address] = dedupe_key

            session = kiosk_session["current"]
            if session is None:
                await handle_idle_reading(reading)
            else:
                await handle_authenticated_reading(session, reading)

    async def watch_session_timeout() -> None:
        while True:
            await asyncio.sleep(1)
            session = kiosk_session["current"]
            if session is not None and (time.monotonic() - session.last_activity) > SESSION_TIMEOUT_SECONDS:
                await end_session("timeout")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        loop_holder["loop"] = asyncio.get_running_loop()
        consumer_task = asyncio.create_task(consume_readings())
        timeout_task = asyncio.create_task(watch_session_timeout())
        await scanner.start()
        logger.info("MiScale Analytics Desktop pronto em http://%s:%d", config.host, config.port)
        try:
            yield
        finally:
            await scanner.stop()
            consumer_task.cancel()
            timeout_task.cancel()
            db.close()

    app = FastAPI(title="MiScale Analytics Desktop", lifespan=lifespan)
    app.state.on_reading = on_reading  # hooks de teste — injetam eventos sem precisar da balança física
    app.state.db = db
    app.state.admin_sessions = admin_sessions
    app.state.kiosk_session = kiosk_session  # hook de teste — manipula o relógio da sessão sem dormir de verdade

    def require_admin(miscale_admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE)):
        admin_id = admin_sessions.resolve(miscale_admin_session)
        if admin_id is None:
            raise HTTPException(status_code=401, detail="sessão de administrador inválida ou expirada")
        admin = db.get_admin(admin_id)
        if admin is None:
            raise HTTPException(status_code=401, detail="administrador não encontrado")
        return admin

    # -- Quiosque: login por documento/sugestão + PIN (RF01, RF03, RF04) -----

    @app.get("/api/kiosk/state")
    async def kiosk_state() -> dict:
        session = kiosk_session["current"]
        if session is None:
            return {"status": "idle"}
        client = db.get_client(session.client_id)
        if client is None:
            return {"status": "idle"}
        return {"status": "authenticated", "client": client.as_dict()}

    @app.get("/api/kiosk/history")
    async def kiosk_history(limit: int = 8) -> list[dict]:
        session = kiosk_session["current"]
        if session is None:
            return []
        return db.list_measurements(session.client_id, limit=limit)

    @app.post("/api/kiosk/login")
    async def kiosk_login(body: KioskLoginIn):
        if body.document is not None:
            client = db.find_client_by_document(body.document)
        else:
            client = db.get_client(body.client_id)  # type: ignore[arg-type]

        if client is None or not db.verify_client_pin(client.id, body.pin):
            return JSONResponse(status_code=401, content={"error": "documento/sugestão ou PIN incorretos"})

        await start_session(client)
        return {"client": client.as_dict()}

    @app.post("/api/kiosk/logout")
    async def kiosk_logout() -> dict:
        await end_session("manual")
        return {"ok": True}

    @app.post("/api/kiosk/touch")
    async def kiosk_touch() -> dict:
        touch_session()
        return {"ok": True}

    # -- Administração: login por e-mail/senha (RF07 — RBAC) ------------------

    @app.post("/api/admin/login")
    async def admin_login(body: AdminLoginIn, response: Response):
        found = db.get_admin_by_email(body.email)
        if found is None or not verify_password(body.password, found[1]):
            return JSONResponse(status_code=401, content={"error": "e-mail ou senha incorretos"})
        admin, _ = found
        token = admin_sessions.create(admin.id)
        response.set_cookie(
            ADMIN_SESSION_COOKIE,
            token,
            httponly=True,
            samesite="lax",
            max_age=ADMIN_SESSION_TTL_SECONDS,
        )
        return {"id": admin.id, "email": admin.email}

    @app.post("/api/admin/logout")
    async def admin_logout(
        response: Response, miscale_admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE)
    ) -> dict:
        admin_sessions.revoke(miscale_admin_session)
        response.delete_cookie(ADMIN_SESSION_COOKIE)
        return {"ok": True}

    @app.get("/api/admin/me")
    async def admin_me(admin=Depends(require_admin)) -> dict:
        return {"id": admin.id, "email": admin.email}

    # -- Clientes (CRUD administrativo) ---------------------------------------

    @app.get("/api/admin/clients")
    async def list_clients(admin=Depends(require_admin)) -> list[dict]:
        return [c.as_dict() for c in db.list_clients()]

    @app.post("/api/admin/clients")
    async def create_client(body: ClientCreateIn, admin=Depends(require_admin)):
        try:
            client = db.create_client(
                full_name=body.full_name,
                document=body.document,
                birthdate=body.birthdate,
                sex=body.sex,
                height_cm=body.height_cm,
                algorithm=body.algorithm,
                pin=body.pin,
                accepted_terms=body.accepted_terms,
            )
        except InvalidClient as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return client.as_dict()

    @app.put("/api/admin/clients/{client_id}")
    async def update_client(client_id: int, body: ClientIn, admin=Depends(require_admin)):
        try:
            client = db.update_client(
                client_id,
                full_name=body.full_name,
                document=body.document,
                birthdate=body.birthdate,
                sex=body.sex,
                height_cm=body.height_cm,
                algorithm=body.algorithm,
            )
        except InvalidClient as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return client.as_dict()

    @app.post("/api/admin/clients/{client_id}/reset-pin")
    async def reset_client_pin(client_id: int, body: PinResetIn, admin=Depends(require_admin)):
        try:
            db.reset_client_pin(client_id, body.new_pin)
        except InvalidClient as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return {"ok": True}

    @app.delete("/api/admin/clients/{client_id}")
    async def delete_client(client_id: int, admin=Depends(require_admin)) -> dict:
        db.delete_client(client_id)
        return {"ok": True}

    @app.get("/api/admin/clients/{client_id}/measurements")
    async def list_measurements(client_id: int, limit: int = 200, admin=Depends(require_admin)) -> list[dict]:
        return db.list_measurements(client_id, limit=limit)

    @app.get("/api/admin/clients/{client_id}/measurements/export")
    async def export_measurements(client_id: int, format: str = "csv", admin=Depends(require_admin)):
        try:
            content, content_type = db.export_measurements(client_id, format)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        extension = "json" if format == "json" else "csv"
        return PlainTextResponse(
            content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="client-{client_id}.{extension}"'},
        )

    @app.get("/api/admin/clients/{client_id}/measurements/{measurement_id}/report")
    async def get_measurement_report(client_id: int, measurement_id: int, admin=Depends(require_admin)):
        client = db.get_client(client_id)
        measurement = db.get_measurement(measurement_id)
        if client is None or measurement is None or measurement["client_id"] != client_id:
            return JSONResponse(status_code=404, content={"error": "medição não encontrada"})
        if measurement.get("bmi") is None:
            # medição só de peso (sem impedância válida) — não há relatório de composição corporal pra gerar
            return JSONResponse(status_code=404, content={"error": "esta medição não tem dados de composição corporal"})

        path = report_path_for(measurement_id)
        if not path.exists():
            # medição de antes deste recurso existir, ou a geração em segundo plano falhou — gera agora
            pdf_bytes = await asyncio.to_thread(generate_measurement_report, client, measurement)
        else:
            pdf_bytes = await asyncio.to_thread(path.read_bytes)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="relatorio-{client_id}-{measurement_id}.pdf"'},
        )

    # -- Fotos de evolução ("antes e depois") ---------------------------------

    @app.get("/api/admin/clients/{client_id}/photos")
    async def list_photos(client_id: int, admin=Depends(require_admin)) -> list[dict]:
        return [p.as_dict() for p in db.list_progress_photos(client_id)]

    @app.post("/api/admin/clients/{client_id}/photos")
    async def upload_photo(client_id: int, file: UploadFile, admin=Depends(require_admin)):
        if db.get_client(client_id) is None:
            return JSONResponse(status_code=404, content={"error": f"cliente {client_id} não existe"})
        if not (file.content_type or "").startswith("image/"):
            return JSONResponse(status_code=422, content={"error": "o arquivo precisa ser uma imagem"})

        content = await file.read()
        if len(content) > MAX_PHOTO_BYTES:
            return JSONResponse(status_code=422, content={"error": "imagem maior que 8 MB"})

        client_dir = PHOTOS_DIR / str(client_id)
        client_dir.mkdir(parents=True, exist_ok=True)
        extension = Path(file.filename or "").suffix or ".jpg"
        disk_path = client_dir / f"{uuid.uuid4().hex}{extension}"
        disk_path.write_bytes(content)

        photo = db.add_progress_photo(
            client_id=client_id, file_path=str(disk_path), content_type=file.content_type
        )
        return photo.as_dict()

    @app.get("/api/admin/clients/{client_id}/photos/{photo_id}/file")
    async def get_photo_file(client_id: int, photo_id: int, admin=Depends(require_admin)):
        photo = db.get_progress_photo(photo_id)
        if photo is None or photo.client_id != client_id:
            return JSONResponse(status_code=404, content={"error": "foto não encontrada"})
        disk_path = Path(photo.file_path)
        if not disk_path.exists():
            return JSONResponse(status_code=404, content={"error": "arquivo da foto não encontrado no disco"})
        return FileResponse(disk_path, media_type=photo.content_type)

    @app.delete("/api/admin/clients/{client_id}/photos/{photo_id}")
    async def delete_photo(client_id: int, photo_id: int, admin=Depends(require_admin)) -> dict:
        photo = db.get_progress_photo(photo_id)
        if photo is not None and photo.client_id == client_id:
            Path(photo.file_path).unlink(missing_ok=True)
            db.delete_progress_photo(photo_id)
        return {"ok": True}

    # -- WebSocket (quiosque) ---------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/admin")
    async def admin_page() -> FileResponse:
        return FileResponse(WEB_DIR / "admin.html")

    return app
