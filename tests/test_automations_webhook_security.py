"""Webhook dispatch security telemetry: anomaly registration, 404 preserved, no secrets."""
import pytest
from sqlalchemy import select

from aios.db.models import AutomationTrigger, Workflow
from aios.governance.security import SECURITY_METRIC_EVENT_TYPES, SecurityEvent


@pytest.mark.asyncio
async def test_webhook_anomaly_metric_registered():
    assert SECURITY_METRIC_EVENT_TYPES["webhook_anomaly"] == "security.webhook.anomaly"


@pytest.mark.asyncio
async def test_webhook_dispatch_signature_anomaly_records_event_preserves_404(async_client, test_db_session, test_org, monkeypatch):
    wf = Workflow(org_id=test_org.id, name="wf-whsec", description="", timeout_seconds=30)
    test_db_session.add(wf)
    await test_db_session.flush()
    trig = AutomationTrigger(
        workflow_id=wf.id,
        org_id=test_org.id,
        type="webhook",
        name="wh",
        config={},
        webhook_path="wh_sec_test_1",
        is_active=True,
    )
    test_db_session.add(trig)
    await test_db_session.commit()

    async def _noop_enqueue(*args, **kwargs):
        return None

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", _noop_enqueue)

    secret = "super-secret-signature-value"
    resp = await async_client.post(
        "/api/automations/webhook/wh_sec_test_1",
        headers={
            "x-hub-signature-256": "",  # obvious anomaly: empty
            "x-slack-signature": secret,  # sensitive; must not be persisted in anomaly payload
            "content-type": "application/json",
        },
        json={"ok": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["workflow_id"] == wf.id

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.webhook.anomaly")
        )
    ).scalars().all()
    assert rows, "expected webhook anomaly security event"
    evt = rows[-1]
    assert evt.org_id == test_org.id
    assert evt.source == "api.automations.webhook_dispatch"
    assert evt.severity in {"medium", "high", "low", "info", "critical"}
    payload = evt.payload or {}
    assert payload.get("reason") == "signature_header_anomaly"
    assert payload.get("workflow_id") == wf.id
    assert payload.get("trigger_id") == trig.id
    anomalies = payload.get("anomalies") or []
    assert "x-hub-signature-256:empty" in anomalies
    # no secret values logged/persisted
    blob = str(payload)
    assert secret not in blob
    assert "super-secret-signature-value" not in blob

    # 404 behavior preserved for missing webhook
    missing = await async_client.post("/api/automations/webhook/wh_does_not_exist", json={"x": 1})
    assert missing.status_code == 404, missing.text
