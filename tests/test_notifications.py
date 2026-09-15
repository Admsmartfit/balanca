"""Testes da notificação desktop "quem está pesando" (PRD seção 13, sugestão 3)."""

from app.notifications import notify_ambiguous_measurement


def test_notify_never_raises_even_if_backend_fails(monkeypatch):
    import plyer

    def _boom(*args, **kwargs):
        raise RuntimeError("sem servidor de notificação disponível")

    monkeypatch.setattr(plyer.notification, "notify", _boom)

    # não deve levantar — leitura da balança não pode travar por causa de notificação (RNF06)
    notify_ambiguous_measurement(72.5, "kg", ["Alice", "Bob"])


def test_notify_calls_plyer_with_expected_fields(monkeypatch):
    import plyer

    calls = []
    monkeypatch.setattr(plyer.notification, "notify", lambda **kwargs: calls.append(kwargs))

    notify_ambiguous_measurement(72.5, "kg", ["Alice", "Bob"])

    assert len(calls) == 1
    assert "72.5" in calls[0]["message"]
    assert "Alice" in calls[0]["message"]
    assert "Bob" in calls[0]["message"]
