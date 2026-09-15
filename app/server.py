"""FastAPI + WebSocket — RF04 (atualizações parciais/finais), RF05/RF06
(perfis com algoritmo por perfil), RF07 (histórico + exportação), RF08
(identificação automática por peso) e RF10 (modo convidado).

Arquitetura (PRD seção 4, modo passivo): o scanner BLE roda na mesma
`asyncio` loop do servidor, publica cada leitura em uma fila, e uma task
separada consome a fila, decide a qual perfil ela pertence, calcula as
métricas quando a leitura está estabilizada e transmite o resultado a todos
os clientes WebSocket conectados.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ble_scanner import MiScaleScanner, ScaleReading
from .config import WEB_DIR, load_config
from .db import DB_PATH, Database, InvalidProfile, Profile
from .engine import BodyMetricsInput, OutOfRangeReading, compute_body_score, compute_metrics
from .matching import MatchStatus, match_profile
from .notifications import notify_ambiguous_measurement

logger = logging.getLogger(__name__)


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


class ProfileIn(BaseModel):
    name: str
    height_cm: float = Field(ge=100, le=220)
    age: int = Field(ge=1, le=99)
    sex: str
    algorithm: str = "xiaomi"


class ConfirmIn(BaseModel):
    pending_id: int
    profile_id: int | None = None  # None => confirmar como convidado


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


def _compute_for_profile(profile: Profile, reading: ScaleReading) -> tuple[dict | None, str | None, bool]:
    """Retorna (métricas ou None, aviso ou None, persistir?) para um perfil + leitura estabilizada.

    Sem impedância válida, o peso ainda é gravado — só as métricas derivadas
    ficam indisponíveis (PRD seção 13, "modo apenas peso"). Uma leitura fora
    dos limites fisiológicos (RNF06) é descartada, não persistida.
    """
    if reading.impedance_ohm is None:
        return None, "sem impedância válida — só o peso foi registrado", True

    body_metrics_input = BodyMetricsInput(
        weight_kg=reading.weight_kg,
        height_cm=profile.height_cm,
        age=profile.age,
        sex=profile.sex,
        impedance_ohm=reading.impedance_ohm,
    )
    try:
        metrics = compute_metrics(profile.algorithm, body_metrics_input)
    except OutOfRangeReading as exc:
        logger.warning("leitura descartada (RNF06): %s", exc)
        return None, f"leitura fora dos limites fisiológicos: {exc}", False

    body_score = compute_body_score(body_metrics_input, metrics)
    return _metrics_to_dict(metrics, body_score), None, True


def create_app(db_path: Path = DB_PATH, *, desktop_notifications: bool = True) -> FastAPI:
    config = load_config()
    db = Database(db_path)
    manager = ConnectionManager()
    reading_queue: asyncio.Queue[ScaleReading] = asyncio.Queue()
    last_seen: dict[str, tuple[float, float | None, bool]] = {}
    pending_readings: dict[int, ScaleReading] = {}
    pending_id_counter = itertools.count(1)
    loop_holder: dict[str, asyncio.AbstractEventLoop] = {}

    def on_reading(reading: ScaleReading) -> None:
        # bleak chama isso na loop do app; testes/hooks externos podem chamar de outra
        # thread (ex.: TestClient) — call_soon_threadsafe cobre os dois casos.
        loop = loop_holder.get("loop")
        if loop is not None:
            loop.call_soon_threadsafe(reading_queue.put_nowait, reading)
        else:
            reading_queue.put_nowait(reading)

    scanner = MiScaleScanner(config.scale_mac_address, on_reading)

    async def handle_stabilized(reading: ScaleReading) -> None:
        profiles = db.list_profiles()
        result = match_profile(profiles, db.last_weight_by_profile(), reading.weight_kg)

        if result.status is MatchStatus.NO_PROFILES:
            await manager.broadcast(
                {
                    "type": "final",
                    "mac_address": reading.mac_address,
                    "weight_kg": reading.weight_kg,
                    "unit": reading.unit,
                    "profile": None,
                    "is_guest": True,
                    "algorithm": None,
                    "metrics": None,
                    "warning": "nenhum perfil cadastrado — medição de convidado",
                }
            )
            return

        if result.status is MatchStatus.MATCHED:
            profile = result.profile
            assert profile is not None
            metrics, warning, persist = _compute_for_profile(profile, reading)
            if persist:
                db.insert_measurement(
                    profile_id=profile.id,
                    weight_kg=reading.weight_kg,
                    unit=reading.unit,
                    impedance_ohm=reading.impedance_ohm,
                    algorithm=profile.algorithm,
                    metrics=metrics,
                )
            await manager.broadcast(
                {
                    "type": "final",
                    "mac_address": reading.mac_address,
                    "weight_kg": reading.weight_kg,
                    "unit": reading.unit,
                    "profile": profile.as_dict(),
                    "is_guest": False,
                    "algorithm": profile.algorithm,
                    "metrics": metrics,
                    "warning": warning,
                }
            )
            return

        # AMBIGUOUS ou NO_MATCH — precisa de confirmação manual (RF08).
        pending_id = next(pending_id_counter)
        pending_readings[pending_id] = reading
        await manager.broadcast(
            {
                "type": "needs_confirmation",
                "pending_id": pending_id,
                "weight_kg": reading.weight_kg,
                "unit": reading.unit,
                "reason": "ambiguous" if result.status is MatchStatus.AMBIGUOUS else "no_match",
                "candidates": [p.as_dict() for p in result.candidates],
            }
        )
        if desktop_notifications:
            await asyncio.to_thread(
                notify_ambiguous_measurement,
                reading.weight_kg,
                reading.unit,
                [p.name for p in result.candidates],
            )

    async def consume_readings() -> None:
        while True:
            reading = await reading_queue.get()
            dedupe_key = (reading.weight_kg, reading.impedance_ohm, reading.stabilized)
            if last_seen.get(reading.mac_address) == dedupe_key:
                continue
            last_seen[reading.mac_address] = dedupe_key

            if not reading.stabilized or reading.removed:
                await manager.broadcast(
                    {
                        "type": "partial",
                        "mac_address": reading.mac_address,
                        "weight_kg": reading.weight_kg,
                        "unit": reading.unit,
                    }
                )
                continue

            await handle_stabilized(reading)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        loop_holder["loop"] = asyncio.get_running_loop()
        consumer_task = asyncio.create_task(consume_readings())
        await scanner.start()
        logger.info("MiScale Analytics Desktop pronto em http://%s:%d", config.host, config.port)
        try:
            yield
        finally:
            await scanner.stop()
            consumer_task.cancel()
            db.close()

    app = FastAPI(title="MiScale Analytics Desktop", lifespan=lifespan)
    app.state.on_reading = on_reading  # hooks de teste — injetam eventos sem precisar da balança física
    app.state.db = db

    # -- Perfis (RF05/RF06) --------------------------------------------------

    @app.get("/api/profiles")
    async def list_profiles() -> list[dict]:
        return [p.as_dict() for p in db.list_profiles()]

    @app.post("/api/profiles")
    async def create_profile(body: ProfileIn):
        try:
            profile = db.create_profile(
                name=body.name, height_cm=body.height_cm, age=body.age, sex=body.sex, algorithm=body.algorithm
            )
        except InvalidProfile as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return profile.as_dict()

    @app.put("/api/profiles/{profile_id}")
    async def update_profile(profile_id: int, body: ProfileIn):
        try:
            profile = db.update_profile(
                profile_id,
                name=body.name,
                height_cm=body.height_cm,
                age=body.age,
                sex=body.sex,
                algorithm=body.algorithm,
            )
        except InvalidProfile as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return profile.as_dict()

    @app.delete("/api/profiles/{profile_id}")
    async def delete_profile(profile_id: int) -> dict:
        db.delete_profile(profile_id)
        return {"ok": True}

    # -- Histórico e exportação (RF07, RF09) ---------------------------------

    @app.get("/api/profiles/{profile_id}/measurements")
    async def list_measurements(profile_id: int, limit: int = 200) -> list[dict]:
        return db.list_measurements(profile_id, limit=limit)

    @app.get("/api/profiles/{profile_id}/measurements/export")
    async def export_measurements(profile_id: int, format: str = "csv"):
        try:
            content, content_type = db.export_measurements(profile_id, format)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        extension = "json" if format == "json" else "csv"
        return PlainTextResponse(
            content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="profile-{profile_id}.{extension}"'},
        )

    # -- Confirmação manual de perfil ambíguo (RF08) -------------------------

    @app.post("/api/measurements/confirm")
    async def confirm_measurement(body: ConfirmIn):
        reading = pending_readings.pop(body.pending_id, None)
        if reading is None:
            return JSONResponse(status_code=404, content={"error": "pending_id não encontrado ou já resolvido"})

        if body.profile_id is None:
            await manager.broadcast(
                {
                    "type": "final",
                    "mac_address": reading.mac_address,
                    "weight_kg": reading.weight_kg,
                    "unit": reading.unit,
                    "profile": None,
                    "is_guest": True,
                    "algorithm": None,
                    "metrics": None,
                    "warning": None,
                }
            )
            return {"ok": True}

        profile = db.get_profile(body.profile_id)
        if profile is None:
            return JSONResponse(status_code=404, content={"error": f"perfil {body.profile_id} não existe"})

        metrics, warning, persist = _compute_for_profile(profile, reading)
        if persist:
            db.insert_measurement(
                profile_id=profile.id,
                weight_kg=reading.weight_kg,
                unit=reading.unit,
                impedance_ohm=reading.impedance_ohm,
                algorithm=profile.algorithm,
                metrics=metrics,
            )
        await manager.broadcast(
            {
                "type": "final",
                "mac_address": reading.mac_address,
                "weight_kg": reading.weight_kg,
                "unit": reading.unit,
                "profile": profile.as_dict(),
                "is_guest": False,
                "algorithm": profile.algorithm,
                "metrics": metrics,
                "warning": warning,
            }
        )
        return {"ok": True}

    # -- WebSocket ------------------------------------------------------------

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

    return app
