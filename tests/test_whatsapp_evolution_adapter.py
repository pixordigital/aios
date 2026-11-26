from typing import Any

from aios.core.adapters.whatsapp_evolution import EvolutionWhatsAppAdapter


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "recipient": "5511999999999",
        "org_id": "org-1",
        "approved": True,
        "text": "hello",
    }
    payload.update(overrides)
    return payload


def test_missing_config_fails_closed():
    adapter = EvolutionWhatsAppAdapter(
        approved=True,
        server_url="",
        api_key="",
        sender=lambda **_: {"ok": True},
    )

    result = adapter.execute(
        action="send_text",
        payload=_base_payload(),
        idempotency_key="idem-config",
    )

    assert result.ok is False
    assert result.status == "not_configured"
    assert "not_configured" in result.detail


def test_missing_approval_fails_closed():
    adapter = EvolutionWhatsAppAdapter(
        approved=False,
        server_url="http://evolution:8080",
        api_key="test-key",
        sender=lambda **_: {"ok": True},
    )

    result = adapter.execute(
        action="send_text",
        payload=_base_payload(approved=False),
        idempotency_key="idem-approval",
    )

    assert result.ok is False
    assert result.status == "denied"
    assert "approval" in result.detail.lower()


def test_approved_injected_sender_returns_ok_and_audit_called():
    events: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []

    def sender(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"provider_message_id": "msg-1"}

    adapter = EvolutionWhatsAppAdapter(
        approved=True,
        server_url="http://evolution:8080",
        api_key="test-key",
        sender=sender,
        audit_callback=events.append,
    )

    result = adapter.execute(
        action="send_text",
        payload=_base_payload(),
        idempotency_key="idem-ok",
    )

    assert result.ok is True
    assert result.status == "ok"
    assert result.adapter == "whatsapp_evolution"
    assert result.idempotency_key == "idem-ok"
    assert len(calls) == 1
    assert calls[0]["recipient"] == "5511999999999"
    assert calls[0]["org_id"] == "org-1"
    assert any(e.get("event") == "whatsapp_evolution.start" for e in events)
    assert any(e.get("event") == "whatsapp_evolution.result" and e.get("ok") is True for e in events)


def test_idempotency_required():
    adapter = EvolutionWhatsAppAdapter(
        approved=True,
        server_url="http://evolution:8080",
        api_key="test-key",
        sender=lambda **_: {"ok": True},
    )

    result = adapter.execute(
        action="send_text",
        payload=_base_payload(),
        idempotency_key="",
    )

    assert result.ok is False
    assert "idempotency_key required" in result.detail
