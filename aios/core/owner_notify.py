"""Owner-facing delivery: Slack primary, Telegram fallback, ack-tracked escalation."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from aios.channels.manager import manager as channel_manager
from aios.channels.telegram import TelegramChannel
from aios.config import settings
from aios.core import meetings
from aios.db.engine import async_session
from aios.db.models import ChannelConnection, OwnerNotification

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _telegram_channels(org_id: str) -> list[TelegramChannel]:
    async with async_session() as db:
        rows = (await db.execute(
            select(ChannelConnection).where(
                ChannelConnection.org_id == org_id,
                ChannelConnection.channel_type == "telegram",
                ChannelConnection.is_active == True,  # noqa: E712
            )
        )).scalars().all()
    out = []
    for row in rows:
        try:
            out.append(channel_manager.build(row))
        except Exception:
            logger.exception("owner_notify: cannot build telegram channel %s", row.id)
    return out


async def send_telegram(org_id: str, text: str) -> bool:
    for ch in await _telegram_channels(org_id):
        try:
            mid = await ch.send(type("M", (), {"text": text, "extra_data": {}})())
            if mid:
                return True
        except Exception:
            logger.exception("owner_notify: telegram fallback failed")
    return False


async def deliver_owner(org_id: str, text: str, urgency: str = "info",
                        requires_ack: bool = False, team_id: str = "") -> dict:
    """Post to Slack DMs; fall back to Telegram if nothing lands."""
    body = text.strip()
    targets = await meetings.human_slack_targets(org_id, team_id=team_id or "")
    sent = []
    for t in targets:
        try:
            if await asyncio.to_thread(meetings.post_to_slack, t["token"], t["channel"], body):
                sent.append(t)
        except Exception:
            logger.exception("owner_notify: slack post failed")

    telegram_ok = False
    if not sent:
        telegram_ok = await send_telegram(org_id, body)

    if requires_ack and urgency in ("blocker", "warning"):
        async with async_session() as db:
            for t in sent:
                db.add(OwnerNotification(
                    org_id=org_id, channel_type="slack", target=t["channel"],
                    body=body, urgency=urgency, requires_ack=True,
                    deadline_at=_now() + timedelta(minutes=settings.owner_ack_timeout_minutes),
                ))
            if not sent and telegram_ok:
                db.add(OwnerNotification(
                    org_id=org_id, channel_type="telegram", target="telegram",
                    body=body, urgency=urgency, requires_ack=True,
                    deadline_at=_now() + timedelta(minutes=settings.owner_ack_timeout_minutes),
                ))
            await db.commit()

    return {
        "ok": bool(sent or telegram_ok),
        "delivered": len(sent),
        "attempted": len(targets),
        "channels": [t["channel"] for t in sent],
        "slack_delivered": len(sent),
        "slack_attempted": len(targets),
        "telegram_delivered": 1 if telegram_ok else 0,
    }


async def ack_notification(org_id: str, channel_type: str, target: str) -> int:
    """Mark the newest pending notification for this target acknowledged.

    shortcut: one reaction/reply acks only the newest pending message; older
    ones still escalate. Upgrade to per-message ts if bursts become common.
    """
    async with async_session() as db:
        row = (await db.execute(
            select(OwnerNotification).where(
                OwnerNotification.org_id == org_id,
                OwnerNotification.channel_type == channel_type,
                OwnerNotification.target == target,
                OwnerNotification.acked_at.is_(None),
            ).order_by(OwnerNotification.created_at.desc())
        )).scalars().first()
        if row is None:
            return 0
        row.acked_at = _now()
        await db.commit()
        return 1


async def escalate_due() -> int:
    """Send Telegram to every unacked notification past its deadline. Returns count."""
    now = _now()
    async with async_session() as db:
        rows = (await db.execute(
            select(OwnerNotification).where(
                OwnerNotification.requires_ack == True,  # noqa: E712
                OwnerNotification.acked_at.is_(None),
                OwnerNotification.escalated_at.is_(None),
                OwnerNotification.deadline_at.is_not(None),
                OwnerNotification.deadline_at <= now,
            )
        )).scalars().all()
    sent = 0
    for r in rows:
        ok = False
        for ch in await _telegram_channels(r.org_id):
            try:
                mid = await ch.send(type("M", (), {"text": r.body, "extra_data": {}})())
                if mid:
                    ok = True
            except Exception:
                logger.exception("owner_notify: escalation send failed %s", r.id)
        if ok:
            async with async_session() as db:
                row = await db.get(OwnerNotification, r.id)
                if row is not None:
                    row.escalated_at = _now()
                    await db.commit()
            sent += 1
    return sent
