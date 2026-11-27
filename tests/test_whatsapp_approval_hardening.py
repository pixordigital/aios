import pytest
from sqlalchemy import select

from aios.db.models import AuditLog, ChannelConnection, PendingAction


def _mk_conn(org_id, instance="wa-1"):
    return ChannelConnection(
        org_id=org_id,
        channel_type="evolution",
        label="WA",
        config={"instance": instance},
        is_active=True,
    )


async def _mk_action(db, *, org_id, tool_name, tool_args, status="approved", decided_by="admin-user"):
    row = PendingAction(
        org_id=org_id,
        tool_name=tool_name,
        tool_args=tool_args,
        status=status,
        decided_by=decided_by if status in {"approved", "rejected", "consumed"} else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _patch_send(monkeypatch, calls):
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


@pytest.mark.asyncio
async def test_whatsapp_send_rejects_approved_true_without_db_evidence(auth_client, test_db_session, test_org, monkeypatch):
    test_db_session.add(_mk_conn(test_org.id))
    await test_db_session.commit()
    calls = {"send": 0}
    _patch_send(monkeypatch, calls)

    resp = await auth_client.post(
        "/api/whatsapp/send",
        json={"instance": "wa-1", "to": "5511999999999", "text": "hi", "provider": "baileys", "approved": True},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "approval_required"
    assert calls["send"] == 0

    logs = (await test_db_session.execute(select(AuditLog).where(AuditLog.action == "whatsapp.send.blocked"))).scalars().all()
    assert any(l.details.get("reason") == "approval_action_id required" for l in logs)


@pytest.mark.asyncio
async def test_whatsapp_send_allows_verified_approved_action_and_consumes(auth_client, test_db_session, test_org, monkeypatch):
    test_db_session.add(_mk_conn(test_org.id))
    await test_db_session.commit()
    action = await _mk_action(
        test_db_session,
        org_id=test_org.id,
        tool_name="whatsapp_template",
        tool_args={"to": "5511999999999", "text": "hi", "instance": "wa-1", "provider": "baileys"},
    )
    calls = {"send": 0}
    _patch_send(monkeypatch, calls)

    resp = await auth_client.post(
        "/api/whatsapp/send",
        json={
            "instance": "wa-1",
            "to": "5511999999999",
            "text": "hi",
            "provider": "baileys",
            "approved": True,
            "approval_action_id": action.id,
        },
    )
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
    assert calls["send"] == 1

    action_id = action.id
    test_db_session.expire(action)
    refreshed = (await test_db_session.execute(
        select(PendingAction).where(PendingAction.id == action_id)
    )).scalar_one()
    assert refreshed.status == "consumed"
    assert refreshed.consumed_at is not None

    logs = (await test_db_session.execute(select(AuditLog).where(AuditLog.org_id == test_org.id))).scalars().all()
    actions = [l.action for l in logs]
    assert "whatsapp.send.approval_consumed" in actions
    assert "whatsapp.send.executed" in actions


@pytest.mark.asyncio
async def test_whatsapp_send_replay_denied(auth_client, test_db_session, test_org, monkeypatch):
    test_db_session.add(_mk_conn(test_org.id))
    await test_db_session.commit()
    action = await _mk_action(
        test_db_session,
        org_id=test_org.id,
        tool_name="whatsapp_template",
        tool_args={"to": "5511999999999", "text": "hi", "instance": "wa-1", "provider": "baileys"},
    )
    calls = {"send": 0}
    _patch_send(monkeypatch, calls)
    payload = {
        "instance": "wa-1",
        "to": "5511999999999",
        "text": "hi",
        "provider": "baileys",
        "approval_action_id": action.id,
    }
    r1 = await auth_client.post("/api/whatsapp/send", json=payload)
    assert r1.status_code == 200
    r2 = await auth_client.post("/api/whatsapp/send", json=payload)
    assert r2.status_code == 409
    assert calls["send"] == 1


@pytest.mark.asyncio
async def test_whatsapp_send_cross_org_action_denied(auth_client, test_db_session, test_org, second_org, monkeypatch):
    test_db_session.add(_mk_conn(test_org.id))
    await test_db_session.commit()
    foreign = await _mk_action(
        test_db_session,
        org_id=second_org.id,
        tool_name="whatsapp_template",
        tool_args={"to": "5511999999999", "text": "hi", "instance": "wa-1", "provider": "baileys"},
    )
    calls = {"send": 0}
    _patch_send(monkeypatch, calls)

    resp = await auth_client.post(
        "/api/whatsapp/send",
        json={
            "instance": "wa-1",
            "to": "5511999999999",
            "text": "hi",
            "provider": "baileys",
            "approval_action_id": foreign.id,
        },
    )
    assert resp.status_code == 409
    assert calls["send"] == 0


@pytest.mark.asyncio
async def test_whatsapp_send_args_mismatch_denied(auth_client, test_db_session, test_org, monkeypatch):
    test_db_session.add(_mk_conn(test_org.id))
    await test_db_session.commit()
    action = await _mk_action(
        test_db_session,
        org_id=test_org.id,
        tool_name="whatsapp_template",
        tool_args={"to": "5511888888888", "text": "different", "instance": "wa-1", "provider": "baileys"},
    )
    calls = {"send": 0}
    _patch_send(monkeypatch, calls)

    resp = await auth_client.post(
        "/api/whatsapp/send",
        json={
            "instance": "wa-1",
            "to": "5511999999999",
            "text": "hi",
            "provider": "baileys",
            "approval_action_id": action.id,
        },
    )
    assert resp.status_code == 409
    assert calls["send"] == 0


@pytest.mark.asyncio
async def test_whatsapp_call_requires_verified_approval(auth_client, test_db_session, test_org, monkeypatch):
    test_db_session.add(_mk_conn(test_org.id))
    await test_db_session.commit()
    calls = {"call": 0}

    async def _start(*_a, **_k):
        calls["call"] += 1
        return {"ok": True}

    monkeypatch.setattr("aios.core.whatsapp.voice.call_router.start_outbound", _start)

    # no approval evidence
    r1 = await auth_client.post(
        "/api/whatsapp/call",
        json={"instance": "wa-1", "to": "5511999999999", "script": "hi", "approved": True},
    )
    assert r1.status_code == 409
    assert calls["call"] == 0

    action = await _mk_action(
        test_db_session,
        org_id=test_org.id,
        tool_name="voice_call",
        tool_args={"to": "5511999999999", "instance": "wa-1", "script": "hi"},
    )
    r2 = await auth_client.post(
        "/api/whatsapp/call",
        json={"instance": "wa-1", "to": "5511999999999", "script": "hi", "approval_action_id": action.id},
    )
    assert r2.status_code == 200
    assert calls["call"] == 1
    action_id = action.id
    test_db_session.expire(action)
    refreshed = (await test_db_session.execute(
        select(PendingAction).where(PendingAction.id == action_id)
    )).scalar_one()
    assert refreshed.status == "consumed"


@pytest.mark.asyncio
async def test_whatsapp_call_cross_org_instance_denied(auth_client, test_db_session, test_org, second_org, monkeypatch):
    test_db_session.add(_mk_conn(second_org.id, instance="wa-other"))
    await test_db_session.commit()
    calls = {"call": 0}

    async def _start(*_a, **_k):
        calls["call"] += 1
        return {"ok": True}

    monkeypatch.setattr("aios.core.whatsapp.voice.call_router.start_outbound", _start)

    action = await _mk_action(
        test_db_session,
        org_id=test_org.id,
        tool_name="voice_call",
        tool_args={"to": "5511999999999", "instance": "wa-other", "script": "hi"},
    )
    resp = await auth_client.post(
        "/api/whatsapp/call",
        json={"instance": "wa-other", "to": "5511999999999", "script": "hi", "approval_action_id": action.id},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "instance not found"
    assert calls["call"] == 0
    refreshed = await test_db_session.get(PendingAction, action.id)
    assert refreshed.status == "approved"
