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
    photometry_enabled: bool
    kiosk_local_only: bool


def load_config() -> AppConfig:
    data: dict = {}
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    photometry: dict = data.get("photometry", {})

    return AppConfig(
        scale_mac_address=data.get("scale_mac_address"),
        host=data.get("host", "127.0.0.1"),
        port=int(data.get("port", 8765)),
        # desligada por padrão: a Etapa 1 (PRD v3 — Fotometria Corporal) só prepara o
        # back-end (banco, consentimento, sessão, rotas); a tela de câmera do quiosque
        # é a Etapa 2, ainda não existe — ligar isto antes dela deixaria a sessão
        # presa esperando fotos que a UI nunca envia.
        photometry_enabled=bool(photometry.get("enabled", False)),
        kiosk_local_only=bool(data.get("kiosk_local_only", True)),
    )
