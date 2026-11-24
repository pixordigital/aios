"""Webhook dispatch security telemetry: anomaly registration, 404 preserved, no secrets."""
import json

import pytest
from sqlalchemy import select

from aios.core.secrets import decrypt_secret, encrypt_secret
from aios.db.models import AutomationTrigger, Credential, CredentialEvent, Workflow
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


@pytest.mark.asyncio
async def test_credential_rotate_reencrypts_and_appends_audit_event(auth_client, test_db_session, test_org, test_user):
    old_secret = "old-rotation-secret"
    cred = Credential(
        org_id=test_org.id,
        name="rotate-me",
        cred_type="bearer",
        data_enc=encrypt_secret(json.dumps({"token": old_secret})),
        version=1,
    )
    test_db_session.add(cred)
    await test_db_session.commit()
    await test_db_session.refresh(cred)

    new_secret = "new-rotation-secret"
    resp = await auth_client.post(
        f"/api/automations/credentials/{cred.id}/rotate",
        json={"data": {"token": new_secret}, "reason": "scheduled rotation"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == cred.id
    assert body["version"] == 2
    assert body["rotated_at"]
    assert new_secret not in resp.text

    await test_db_session.refresh(cred)
    assert cred.version == 2
    assert cred.rotated_at is not None
    assert decrypt_secret(cred.data_enc) == json.dumps({"token": new_secret})

    events = (
        await test_db_session.execute(
            select(CredentialEvent).where(CredentialEvent.credential_id == cred.id)
        )
    ).scalars().all()
    assert len(events) == 1
    event = events[0]
    assert event.org_id == test_org.id
    assert event.event == "rotated"
    assert event.actor_user_id == test_user.id
    assert event.from_version == 1
    assert event.to_version == 2
    assert event.details == {"reason": "scheduled rotation"}

    audit = await auth_client.get(f"/api/automations/credentials/{cred.id}/events")
    assert audit.status_code == 200, audit.text
    rows = audit.json()
    assert len(rows) == 1
    assert rows[0]["actor_user_id"] == test_user.id
    assert rows[0]["from_version"] == 1
    assert rows[0]["to_version"] == 2
    assert rows[0]["details"] == {"reason": "scheduled rotation"}
    assert "data_enc" not in rows[0]
    assert new_secret not in audit.text


@pytest.mark.asyncio
async def test_credential_rotation_endpoints_are_org_scoped(auth_client, test_db_session, second_org):
    cred = Credential(
        org_id=second_org.id,
        name="other-org-cred",
        cred_type="bearer",
        data_enc=encrypt_secret(json.dumps({"token": "other-org-secret"})),
        version=1,
    )
    test_db_session.add(cred)
    await test_db_session.commit()
    await test_db_session.refresh(cred)

    rotate = await auth_client.post(
        f"/api/automations/credentials/{cred.id}/rotate",
        json={"data": {"token": "replacement"}, "reason": "cross-org attempt"},
    )
    assert rotate.status_code == 404, rotate.text
    audit = await auth_client.get(f"/api/automations/credentials/{cred.id}/events")
    assert audit.status_code == 404, audit.text

    await test_db_session.refresh(cred)
    assert cred.version == 1
    assert decrypt_secret(cred.data_enc) == json.dumps({"token": "other-org-secret"})
