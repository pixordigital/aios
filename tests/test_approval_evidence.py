from datetime import datetime, timedelta, timezone

import pytest

from aios.core.approval_evidence import verify_and_consume_approval
from aios.db.models import PendingAction


async def _mk_action(db, *, org_id="org-1", tool_name="whatsapp_template", tool_args=None, status="approved", decided_by="admin-user", consumed_at=None):
    row = PendingAction(
        org_id=org_id,
        tool_name=tool_name,
        tool_args=tool_args or {"to": "5511999999999"},
        status=status,
        decided_by=decided_by if status in {"approved", "rejected", "consumed"} else None,
        consumed_at=consumed_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest.mark.asyncio
async def test_verify_and_consume_happy_path(test_db_session):
    action = await _mk_action(test_db_session, org_id="org-1", tool_name="tool_x", tool_args={"k": "v"})

    res = await verify_and_consume_approval(
        test_db_session,
        org_id="org-1",
        approval_action_id=action.id,
        expected_tool_name="tool_x",
        args_match=lambda args: isinstance(args, dict) and args.get("k") == "v",
    )
    assert res.ok is True
    assert res.reason == "ok"
    refreshed = await test_db_session.get(PendingAction, action.id)
    assert refreshed.status == "consumed"
    assert refreshed.consumed_at is not None


@pytest.mark.asyncio
async def test_verify_and_consume_fail_closed_cases(test_db_session, second_org):
    action = await _mk_action(test_db_session, org_id="org-1", tool_name="tool_x", tool_args={"k": "v"})

    missing = await verify_and_consume_approval(test_db_session, org_id="org-1", approval_action_id=None, expected_tool_name="tool_x")
    assert missing.ok is False
    assert missing.details["reason"] == "missing_approval_action_id"

    cross = await verify_and_consume_approval(test_db_session, org_id=second_org.id, approval_action_id=action.id, expected_tool_name="tool_x")
    assert cross.ok is False
    assert cross.details["reason"] == "org_mismatch"

    bad_tool = await verify_and_consume_approval(test_db_session, org_id="org-1", approval_action_id=action.id, expected_tool_name="other")
    assert bad_tool.ok is False
    assert bad_tool.details["reason"] == "tool_mismatch"

    bad_args = await verify_and_consume_approval(
        test_db_session, org_id="org-1", approval_action_id=action.id, expected_tool_name="tool_x", args_match=lambda _a: False
    )
    assert bad_args.ok is False
    assert bad_args.details["reason"] == "args_mismatch"


@pytest.mark.asyncio
async def test_verify_and_consume_replay_denied(test_db_session):
    action = await _mk_action(test_db_session, org_id="org-1", tool_name="tool_x", tool_args={"k": "v"})
    ok = await verify_and_consume_approval(test_db_session, org_id="org-1", approval_action_id=action.id, expected_tool_name="tool_x")
    assert ok.ok is True
    replay = await verify_and_consume_approval(test_db_session, org_id="org-1", approval_action_id=action.id, expected_tool_name="tool_x")
    assert replay.ok is False
    assert replay.details["reason"] in {"already_consumed", "consume_race", "not_approved"}


@pytest.mark.asyncio
async def test_verify_and_consume_requires_decided_by_and_not_expired(test_db_session):
    no_decider = await _mk_action(test_db_session, org_id="org-1", tool_name="tool_x", status="approved", decided_by=None)
    res = await verify_and_consume_approval(test_db_session, org_id="org-1", approval_action_id=no_decider.id, expected_tool_name="tool_x")
    assert res.ok is False
    assert res.details["reason"] == "missing_decided_by"

    action = await _mk_action(test_db_session, org_id="org-1", tool_name="tool_x")
    expired = await verify_and_consume_approval(
        test_db_session,
        org_id="org-1",
        approval_action_id=action.id,
        expected_tool_name="tool_x",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert expired.ok is False
    assert expired.details["reason"] == "expired"
