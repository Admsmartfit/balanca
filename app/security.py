"""Hash de PIN/senha, validação de documento e sessão de administrador.

RNF01: PINs e senhas nunca ficam em texto plano — hash com bcrypt (custo
padrão da biblioteca) e salt único por registro, gerado automaticamente
pelo `bcrypt.gensalt()`.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

import bcrypt

PIN_LENGTH = 4


class InvalidPin(ValueError):
    pass


class InvalidPassword(ValueError):
    pass


class InvalidDocument(ValueError):
    pass


def hash_pin(pin: str) -> str:
    if not (pin.isdigit() and len(pin) == PIN_LENGTH):
        raise InvalidPin(f"o PIN deve ter exatamente {PIN_LENGTH} dígitos numéricos")
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pin.encode(), pin_hash.encode())
    except (ValueError, AttributeError):
        return False


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise InvalidPassword("a senha deve ter pelo menos 8 caracteres")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, AttributeError):
        return False


def normalize_document(raw: str) -> str:
    """Mantém só os dígitos de um CPF ou telefone digitado."""
    return "".join(ch for ch in raw if ch.isdigit())


def validate_document(raw: str) -> str:
    """Normaliza e valida um CPF ou telefone como chave de login (RF02).

    Sem checagem de dígito verificador de CPF: um número de telefone de 11
    dígitos é indistinguível de um CPF de 11 dígitos sem um indicador
    explícito de tipo, e rejeitar por checksum arriscaria recusar um
    telefone válido. A validação aqui é só de formato — 10 a 11 dígitos,
    típico de CPF (11) ou telefone brasileiro com/sem o 9º dígito (10-11).
    """
    digits = normalize_document(raw)
    if not (10 <= len(digits) <= 11):
        raise InvalidDocument("CPF ou telefone deve ter 10 ou 11 dígitos")
    return digits


# ---------------------------------------------------------------------------
# Sessão do administrador (RF07 — RBAC)
# ---------------------------------------------------------------------------

ADMIN_SESSION_COOKIE = "miscale_admin_session"
ADMIN_SESSION_TTL_SECONDS = 8 * 60 * 60  # 8 horas


@dataclass(frozen=True, slots=True)
class AdminSession:
    admin_id: int
    expires_at: float


class AdminSessionStore:
    """Sessões de admin em memória — reinicia o servidor, reinicia o login.

    Suficiente para um único processo local (RNF04); não sobrevive a
    restart nem escala para múltiplas instâncias, o que está fora do
    escopo de uma balança doméstica/de consultório único.
    """

    def __init__(self, ttl_seconds: float = ADMIN_SESSION_TTL_SECONDS) -> None:
        self._sessions: dict[str, AdminSession] = {}
        self._ttl = ttl_seconds

    def create(self, admin_id: int) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = AdminSession(admin_id=admin_id, expires_at=time.monotonic() + self._ttl)
        return token

    def resolve(self, token: str | None) -> int | None:
        if token is None:
            return None
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.expires_at < time.monotonic():
            del self._sessions[token]
            return None
        return session.admin_id

    def revoke(self, token: str | None) -> None:
        if token is not None:
            self._sessions.pop(token, None)
