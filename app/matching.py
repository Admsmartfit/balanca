"""Motor de sugestão por peso — RF04 do PRD de cadastro/autenticação.

Sugere até N clientes cujo último peso registrado esteja dentro de uma
tolerância do peso atual da balança, para exibir como atalho de login no
quiosque (a pessoa toca no nome sugerido em vez de digitar o documento
inteiro no teclado numérico). A confirmação de identidade continua sendo
sempre o PIN — a sugestão só acelera achar o cartão certo, nunca autentica
sozinha.
"""

from __future__ import annotations

from .db import Client

DEFAULT_TOLERANCE_KG = 2.0
DEFAULT_LIMIT = 3


def suggest_clients_by_weight(
    clients: list[Client],
    last_weight_by_client: dict[int, float],
    measured_weight_kg: float,
    *,
    tolerance_kg: float = DEFAULT_TOLERANCE_KG,
    limit: int = DEFAULT_LIMIT,
) -> list[Client]:
    """Retorna até `limit` clientes com histórico de peso próximo, do mais perto ao mais longe."""
    candidates = [
        (abs(last_weight_by_client[client.id] - measured_weight_kg), client)
        for client in clients
        if client.id in last_weight_by_client
        and abs(last_weight_by_client[client.id] - measured_weight_kg) <= tolerance_kg
    ]
    candidates.sort(key=lambda pair: pair[0])
    return [client for _, client in candidates[:limit]]
