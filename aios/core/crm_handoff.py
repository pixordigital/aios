"""Guarantee that an inbound conversation leaves a trail the next agent can use.

An SDR that answers a WhatsApp message was leaving nothing behind. The lead only
reached the CRM if the agent happened to call `crm_create_deal`, and nothing
recorded what was said. So a Closer picking up the deal inherited a name and a
phone number and no context at all -- the entire conversation lived in the SDR's
context window, which is discarded when the run ends.

This module is the handoff. It does not try to be smart about what an SDR said;
it makes the interaction durable, which is the part that was missing:

- the contact has a deal, matched on phone, so lead data accumulates on one row
  instead of a new deal per message;
- the exchange is written to `extra_data["last_summary"]` and `last_contacted_at`;
- `CrmDealVersion` gets a row, so the audit trail shows the SDR touched it.

Every entry point fails soft. An unreachable database must not cost the customer
their reply, so callers wrap these and log; nothing here raises into the
inbound path.

Both writes `flush()` rather than `commit()`: they join the caller's transaction
on purpose, so a rollback of the surrounding inbound work takes the CRM write
with it instead of leaving a deal describing a reply that was never sent. The
caller commits.
"""

from datetime import datetime, timezone


def _digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def ensure_deal_for_contact(
    db,
    org_id: str,
    phone: str | None = None,
    name: str | None = None,
    source: str = "whatsapp",
) -> str | None:
    """Return the id of the contact's deal, creating one if this is a new contact.

    Matched on phone digits so the same lead does not accumulate a new deal per
    message. A contact with no phone at all cannot be matched, and creating a
    fresh deal on every message would be worse than not recording it -- so a
    phone is required.
    """
    if not org_id:
        return None
    want = _digits(phone)
    if not want:
        return None

    from sqlalchemy import select

    from aios.db.models import CrmDeal

    rows = (
        await db.execute(
            select(CrmDeal).where(
                CrmDeal.org_id == org_id,
                CrmDeal.stage.notin_(("closed_won", "closed_lost")),
            )
        )
    ).scalars().all()

    for d in rows:
        if _digits(d.lead_phone) == want:
            # A first message carrying a name is better than an empty one.
            if name and not d.lead_name:
                d.lead_name = name
            await db.flush()
            return d.id

    deal = CrmDeal(
        org_id=org_id,
        lead_name=name or "",
        lead_phone=phone or "",
        stage="prospection",
        source=source,
        extra_data={"sdr_touched": True},
    )
    db.add(deal)
    await db.flush()
    return deal.id


async def record_interaction(
    db,
    deal_id: str,
    org_id: str,
    agent_id: str | None,
    inbound_text: str,
    reply_text: str = "",
    field: str = "sdr_conversation",
) -> None:
    """Write one exchange onto the deal so the next agent inherits it."""
    from aios.db.models import CrmDealVersion

    now = datetime.now(timezone.utc)
    summary_parts = [p for p in (inbound_text, reply_text) if p]
    summary = _truncate(" | ".join(summary_parts), 1500)

    deal = None
    try:
        from sqlalchemy import select

        from aios.db.models import CrmDeal

        deal = (
            await db.execute(select(CrmDeal).where(CrmDeal.id == deal_id, CrmDeal.org_id == org_id))
        ).scalar_one_or_none()
    except Exception:
        deal = None

    if deal is not None:
        extra = dict(deal.extra_data or {})
        history = list(extra.get("sdr_history") or [])
        history.append(
            {"at": now.isoformat(), "agent_id": agent_id, "summary": summary[:600]}
        )
        # Keep the tail: the recent exchanges are what the next agent needs.
        extra["sdr_history"] = history[-10:]
        extra["last_contacted_at"] = now.isoformat()
        if summary:
            extra["last_summary"] = _truncate(summary, 600)
        deal.extra_data = extra
        await db.flush()

    db.add(
        CrmDealVersion(
            deal_id=deal_id,
            org_id=org_id,
            changed_by=agent_id,
            changed_by_type="agent",
            field=field,
            old_value="",
            new_value=_truncate(summary, 500),
            extra_data={"at": now.isoformat()},
        )
    )
    await db.flush()