import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from aios.core import owner_notify
from aios.db.models import OwnerNotification, Organization
from sqlalchemy import select


class _FakeChannel:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg.text)
        if not self.ok:
            raise RuntimeError("telegram down")
        return "1"


@pytest.mark.asyncio
async def test_slack_ok_no_telegram_no_pending_if_info(test_session, test_org):
    targets = [{"token": "t", "channel": "C1"}]
    with patch("aios.core.meetings.human_slack_targets", AsyncMock(return_value=targets)), \
         patch("aios.core.meetings.post_to_slack", return_value=True), \
         patch("aios.core.owner_notify._telegram_channels", AsyncMock(return_value=[])):
        res = await owner_notify.deliver_owner(test_org.id, "hi", urgency="info", requires_ack=True)
    assert res["slack_delivered"] == 1
    assert res["telegram_delivered"] == 0
    rows = (await test_session.execute(select(OwnerNotification))).scalars().all()
    assert len(rows) == 0  # info never creates pending


@pytest.mark.asyncio
async def test_blocker_creates_pending(test_session, test_org):
    targets = [{"token": "t", "channel": "C1"}]
    with patch("aios.core.meetings.human_slack_targets", AsyncMock(return_value=targets)), \
         patch("aios.core.meetings.post_to_slack", return_value=True), \
         patch("aios.core.owner_notify._telegram_channels", AsyncMock(return_value=[])):
        await owner_notify.deliver_owner(test_org.id, "boom", urgency="blocker", requires_ack=True)
    rows = (await test_session.execute(select(OwnerNotification))).scalars().all()
    assert len(rows) == 1
    assert rows[0].channel_type == "slack"
    assert rows[0].target == "C1"


@pytest.mark.asyncio
async def test_slack_fail_sends_telegram(test_session, test_org):
    targets = [{"token": "t", "channel": "C1"}]
    ch = _FakeChannel(ok=True)
    with patch("aios.core.meetings.human_slack_targets", AsyncMock(return_value=targets)), \
         patch("aios.core.meetings.post_to_slack", return_value=False), \
         patch("aios.core.owner_notify._telegram_channels", AsyncMock(return_value=[ch])):
        res = await owner_notify.deliver_owner(test_org.id, "boom", urgency="warning", requires_ack=True)
    assert res["slack_delivered"] == 0
    assert res["telegram_delivered"] == 1
    assert ch.sent == ["boom"]


@pytest.mark.asyncio
async def test_ack_by_target(test_session, test_org):
    async with __import__("aios.db.engine", fromlist=["async_session"]).async_session() as db:
        db.add(OwnerNotification(org_id=test_org.id, channel_type="slack", target="C1",
                                body="x", urgency="blocker", requires_ack=True))
        await db.commit()
    n = await owner_notify.ack_notification(test_org.id, "slack", "C1")
    assert n == 1


@pytest.mark.asyncio
async def test_escalate_due_sends_and_marks(test_session, test_org):
    from datetime import datetime, timedelta, timezone
    async with __import__("aios.db.engine", fromlist=["async_session"]).async_session() as db:
        db.add(OwnerNotification(org_id=test_org.id, channel_type="slack", target="C1",
                                body="x", urgency="blocker", requires_ack=True,
                                deadline_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)))
        await db.commit()
    ch = _FakeChannel(ok=True)
    with patch("aios.core.owner_notify._telegram_channels", AsyncMock(return_value=[ch])):
        n = await owner_notify.escalate_due()
    assert n == 1
    rows = (await test_session.execute(select(OwnerNotification))).scalars().all()
    assert rows[0].escalated_at is not None
