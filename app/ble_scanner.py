"""Varredura passiva BLE da Xiaomi Mi Body Composition Scale 2 (RF01/RF02).

Decodifica o payload de 13 bytes do serviço de anúncio ``0000181b``. A
leitura dos bits de controle segue a versão corrigida do PRD (seção 11,
item 5): o byte de controle 0 carrega só a unidade, o byte de controle 1
carrega estabilizado/impedância-válida/removido — confirmado de forma
independente em ``vendor/lolouk44_xiaomi_mi_scale`` (Python) e
``vendor/oliexdev_openScale`` (Kotlin, ``MiScaleHandler.kt::parseLive13``,
usado aqui só como referência de leitura, não como código copiado).
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Callable

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

logger = logging.getLogger(__name__)

SERVICE_UUID_V2 = "0000181b-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True, slots=True)
class ScaleReading:
    mac_address: str
    weight_kg: float
    unit: str  # "kg" | "lbs" | "jin"
    impedance_ohm: float | None
    stabilized: bool
    removed: bool


def parse_v2_payload(data: bytes) -> ScaleReading | None:
    """Decodifica os 13 bytes brutos do serviço 0000181b. ``None`` se malformado."""
    if len(data) != 13:
        logger.debug("payload com tamanho inesperado: %d bytes", len(data))
        return None

    c0, c1 = data[0], data[1]
    is_lbs = bool(c0 & (1 << 0))
    is_catty = bool(c1 & (1 << 6))
    stabilized = bool(c1 & (1 << 5))
    removed = bool(c1 & (1 << 7))
    has_impedance = bool(c1 & (1 << 1))

    weight_raw = data[11] | (data[12] << 8)
    if is_lbs:
        unit, weight_kg = "lbs", weight_raw / 100.0
    elif is_catty:
        unit, weight_kg = "jin", weight_raw / 100.0
    else:
        unit, weight_kg = "kg", weight_raw / 200.0

    impedance: float | None = None
    if has_impedance:
        raw_impedance = data[9] | (data[10] << 8)
        if raw_impedance > 0:
            impedance = float(raw_impedance)

    return ScaleReading(
        mac_address="",
        weight_kg=round(weight_kg, 2),
        unit=unit,
        impedance_ohm=impedance,
        stabilized=stabilized,
        removed=removed,
    )


class MiScaleScanner:
    """Escuta anúncios BLE passivamente e chama ``on_reading`` a cada pacote válido."""

    def __init__(self, mac_address: str | None, on_reading: Callable[[ScaleReading], None]) -> None:
        self._mac_address = mac_address.lower() if mac_address else None
        self._on_reading = on_reading
        self._scanner: BleakScanner | None = None

    def _detection_callback(self, device: BLEDevice, advertisement_data: AdvertisementData) -> None:
        if self._mac_address and device.address.lower() != self._mac_address:
            return

        raw = advertisement_data.service_data.get(SERVICE_UUID_V2)
        if raw is None:
            return

        reading = parse_v2_payload(bytes(raw))
        if reading is None:
            return

        reading = dataclasses.replace(reading, mac_address=device.address)
        try:
            self._on_reading(reading)
        except Exception:
            logger.exception("erro processando leitura de %s", device.address)

    async def start(self) -> None:
        logger.info(
            "iniciando varredura BLE passiva (mac=%s)", self._mac_address or "qualquer"
        )
        self._scanner = BleakScanner(detection_callback=self._detection_callback)
        await self._scanner.start()

    async def stop(self) -> None:
        if self._scanner is not None:
            await self._scanner.stop()
            self._scanner = None
