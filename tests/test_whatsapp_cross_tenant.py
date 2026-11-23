"""Cross-tenant 404 metric regressions for WhatsApp gateway endpoints."""

import pytest
from sqlalchemy import select

from aios.db.models import ChannelConnection
from aios.governance.security import SecurityEvent


async def _cross_tenant_rows(db):
    return (
        await db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()


@pytest.mark.asyncio
async def test_whatsapp_health_cross_tenant_emits_metric(auth_client, test_db_session, second_org, monkeypatch):
    chan = ChannelConnection(
        org_id=second_org.id,
        channel_type="evolution",
        label="Other WA",
        config={"instance": "other-wa-health"},
        is_active=True,
    )
    test_db_session.add(chan)
    await test_db_session.commit()

    class _P:
        provider = "baileys"

        async def health(self, instance):
            raise AssertionError("provider.health should not be called on cross-tenant 404")

    monkeypatch.setattr("aios.core.whatsapp.provider.factory.get_provider", lambda *_a, **_k: _P())
    monkeypatch.setattr("aios.core.whatsapp.anti_ban.health_monitor.compute", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("compute should not run")))

    resp = await auth_client.get("/api/whatsapp/health/other-wa-health")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "instance not found"

    rows = await _cross_tenant_rows(test_db_session)
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "ChannelConnection"
        and e.payload.get("resource_org_id") == second_org.id
        and e.payload.get("instance") == "other-wa-health"
        and e.source == "whatsapp.api.health_instance_not_found"
        for e in rows
    )


@pytest.mark.asyncio
async def test_whatsapp_health_unknown_no_cross_tenant_metric(auth_client, test_db_session, monkeypatch):
    class _P:
        provider = "baileys"

        async def health(self, instance):
            raise AssertionError("provider.health should not be called on unknown 404")

    monkeypatch.setattr("aios.core.whatsapp.provider.factory.get_provider", lambda *_a, **_k: _P())

    resp = await auth_client.get("/api/whatsapp/health/no-such-instance")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "instance not found"

    rows = await _cross_tenant_rows(test_db_session)
    assert not any(e.payload.get("metric") == "cross_tenant_block" for e in rows)


@pytest.mark.asyncio
async def test_whatsapp_send_cross_tenant_emits_metric_and_no_outbound(auth_client, test_db_session, second_org, monkeypatch):
    chan = ChannelConnection(
        org_id=second_org.id,
        channel_type="evolution",
        label="Other WA",
        config={"instance": "other-wa-send"},
        is_active=True,
    )
    test_db_session.add(chan)
    await test_db_session.commit()

    calls = {"send": 0}

    async def _send(*_a, **_k):
        calls["send"] += 1
        return {"ok": True}

    monkeypatch.setattr("aios.core.whatsapp.service.send_via_gateway", _send)
    monkeypatch.setattr("aios.core.whatsapp.anti_ban.rate_limiter.allow", lambda *_a, **_k: True)
    monkeypatch.setattr("aios.core.whatsapp.anti_ban.rate_limiter.record_429", lambda *_a, **_k: None)

    class _Metric:
        def labels(self, **_k):
            return self

        def inc(self, *_a, **_k):
            return None

    monkeypatch.setattr("aios.core.whatsapp.metrics.msg_total", _Metric())

    resp = await auth_client.post(
        "/api/whatsapp/send",
        json={"instance": "other-wa-send", "to": "5511999999999", "text": "hi", "provider": "baileys"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "instance not found"
    assert calls["send"] == 0

    rows = await _cross_tenant_rows(test_db_session)
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "ChannelConnection"
        and e.payload.get("resource_org_id") == second_org.id
        and e.payload.get("instance") == "other-wa-send"
        and e.source == "whatsapp.api.send_instance_not_found"
        for e in rows
    )


@pytest.mark.asyncio
async def test_whatsapp_send_unknown_no_cross_tenant_metric_no_outbound(auth_client, test_db_session, monkeypatch):
    calls = {"send": 0}

    async def _send(*_a, **_k):
        calls["send"] += 1
        return {"ok": True}

    monkeypatch.setattr("aios.core.whatsapp.service.send_via_gateway", _send)
    monkeypatch.setattr("aios.core.whatsapp.anti_ban.rate_limiter.allow", lambda *_a, **_k: True)
    monkeypatch.setattr("aios.core.whatsapp.anti_ban.rate_limiter.record_429", lambda *_a, **_k: None)

    class _Metric:
        def labels(self, **_k):
            return self

        def inc(self, *_a, **_k):
            return None

    monkeypatch.setattr("aios.core.whatsapp.metrics.msg_total", _Metric())

    resp = await auth_client.post(
        "/api/whatsapp/send",
        json={"instance": "missing-wa-send", "to": "5511999999999", "text": "hi", "provider": "baileys"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "instance not found"
    assert calls["send"] == 0

    rows = await _cross_tenant_rows(test_db_session)
    assert not any(e.payload.get("metric") == "cross_tenant_block" for e in rows)
