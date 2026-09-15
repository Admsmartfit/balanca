"""Configuração da aplicação — lida de config.json na raiz do projeto (RNF04: local, sem nuvem)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"
WEB_DIR = ROOT_DIR / "web"


@dataclass(frozen=True, slots=True)
class AppConfig:
    scale_mac_address: str | None
    host: str
    port: int


def load_config() -> AppConfig:
    data: dict = {}
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    return AppConfig(
        scale_mac_address=data.get("scale_mac_address"),
        host=data.get("host", "127.0.0.1"),
        port=int(data.get("port", 8765)),
    )
