"""Notificação desktop "quem está pesando" (PRD seção 13, sugestão 3).

Ideia adaptada do ``NotificationCoordinator`` do bodymiscale (notificação
push interativa no celular) para uma notificação desktop simples — sem app
mobile companheiro, sem servidor externo (RNF04). Usa ``plyer``, que escolhe
o backend nativo certo por SO (toast no Windows, libnotify no Linux).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify_ambiguous_measurement(weight_kg: float, unit: str, candidate_names: list[str]) -> None:
    """Dispara uma notificação desktop quando uma pesagem precisa de confirmação manual (RF08).

    Melhor esforço: qualquer falha (sem servidor de notificação no Linux,
    SO sem suporte, etc.) só gera um aviso no log — nunca derruba o fluxo
    de leitura da balança.
    """
    try:
        from plyer import notification

        notification.notify(
            title="MiScale Analytics — de quem é essa pesagem?",
            message=f"{weight_kg:.1f} {unit} — candidatos: {', '.join(candidate_names)}",
            app_name="MiScale Analytics Desktop",
            timeout=15,
        )
    except Exception:
        logger.warning("não foi possível exibir a notificação desktop", exc_info=True)
