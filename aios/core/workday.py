"""The daily board an agent works, built from state it already owns.

An employee clocks in and knows what is on their plate because the work is
tracked somewhere durable. Agents had no equivalent: `signals.rank_queue` built
a "fila do dia" for the dashboard and for an API, and no agent ever worked it.

So the board is not a new table. It is the open deals the agent owns, ranked by
the timing score that already existed, plus whatever follow-up came due. CRM
state *is* the memory: yesterday's work shows up as a moved stage, a refreshed
`last_contacted_at`, or a pushed `next_follow_up`, so tomorrow's board is
different without anything having to remember it.

SDR and support are excluded on purpose. They are reactive: they act when a
message arrives, and their work arrives as events rather than being pulled from
a board. Putting them on a daily queue would have them prospecting deals that
already have a live conversation open.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from aios.core.signals import OPEN_STAGES, rank_queue

# Agents whose day is driven by inbound traffic, not by a board they pull.
REACTIVE_AGENT_TYPES = frozenset({"sdr", "support"})

DEFAULT_BOARD_SIZE = 10

# Org-level master switch, read from Organization.extra_data. Off by default:
# switching it on starts every eligible agent spending tokens each morning, so
# this is something an operator turns on deliberately rather than something a
# deploy turns on for them.
WORKDAY_ENABLED_KEY = "workday_enabled"


def org_workday_enabled(org) -> bool:
    """Whether this org has opted its agents into a daily board.

    The org switch is absolute: with it off nothing runs, whatever an
    individual agent's own flag says. A paused company should not keep agents
    working because one of them was configured individually before the pause.
    """
    if org is None:
        return False
    return (getattr(org, "extra_data", None) or {}).get(WORKDAY_ENABLED_KEY) is True


def should_work_day(agent) -> bool:
    """Whether this agent gets a daily board.

    Opt out per agent with `extra_data["workday"] = False`, which is cheaper
    than a schema change and needs no migration to roll out.
    """
    if agent.status != "active":
        return False
    if (agent.agent_type or "") in REACTIVE_AGENT_TYPES:
        return False
    if (agent.extra_data or {}).get("workday") is False:
        return False
    return True


def _overdue(deal, now: datetime) -> str | None:
    """A due follow-up that has already passed, as an ISO timestamp."""
    raw = (deal.extra_data or {}).get("next_follow_up")
    if not raw:
        return None
    try:
        due = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return raw if due <= now else None


async def board_for_agent(agent, db, limit: int = DEFAULT_BOARD_SIZE) -> dict:
    """The agent's board for today: its open deals, best first.

    Follow-ups that came due are lifted to the front regardless of timing
    score. A deal the agent promised to call back about today is more urgent
    than a hot lead that happens to score higher, and burying it under a score
    sort is how a promise gets missed.
    """
    now = datetime.now(timezone.utc)
    from aios.db.models import CrmDeal

    rows = (
        await db.execute(
            select(CrmDeal).where(
                CrmDeal.org_id == agent.org_id,
                CrmDeal.agent_id == agent.id,
                CrmDeal.stage.in_(OPEN_STAGES),
            )
        )
    ).scalars().all()

    ranked = rank_queue(rows, limit=limit, now=now)

    items = []
    for r in ranked:
        deal = r["deal"]
        ex = deal.extra_data or {}
        items.append(
            {
                "deal_id": deal.id,
                "lead": deal.lead_name or deal.lead_email or deal.lead_phone or deal.id,
                "stage": deal.stage,
                "value": deal.value,
                "timing": r["timing"],
                "why": r["reasons"],
                "hours_since_touch": r["hours_since_touch"],
                "next_follow_up": ex.get("next_follow_up", ""),
                "follow_up_note": ex.get("next_follow_up_note", ""),
                "due_overdue": _overdue(deal, now),
                "summary": ex.get("last_summary", ""),
            }
        )

    # Due-today first, then keep the timing order within each group.
    items.sort(key=lambda i: (i["due_overdue"] is None, -i["timing"]))

    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "org_id": agent.org_id,
        "date": now.date().isoformat(),
        "count": len(items),
        "overdue": sum(1 for i in items if i["due_overdue"]),
        "items": items,
    }


def render_board(board: dict) -> str:
    """Turn a board into the instruction the agent receives.

    A named function for the same reason `render_event_instruction` is: the
    wording is what every proactive agent's behaviour hangs off, so changing it
    silently would change all of them.
    """
    if not board["count"]:
        return ""

    overdue = board["overdue"]
    head = f"[workday] {board['date']} — {board['count']} item(s) na sua fila"
    if overdue:
        head += f", {overdue} com follow-up vencido"
    head += ".\n\n"

    rows = []
    for i, it in enumerate(board["items"], 1):
        bits = [f"stage={it['stage']}"]
        if it["value"]:
            bits.append(f"R$ {it['value']:.0f}")
        if it["due_overdue"]:
            bits.append(f"FOLLOW_UP VENCIDO em {it['due_overdue']}")
        elif it["next_follow_up"]:
            bits.append(f"follow-up {it['next_follow_up']}")
        if it["hours_since_touch"] is not None:
            bits.append(f"{it['hours_since_touch']}h sem toque")
        rows.append(
            f"{i}. deal_id={it['deal_id']} | {it['lead']} | {' | '.join(bits)}"
            + (f"\n   follow-up: {it['follow_up_note']}" if it["follow_up_note"] else "")
            + (f"\n   resumo anterior: {it['summary']}" if it["summary"] else "")
        )

    return (
        head
        + "\n".join(rows)
        + "\n\nVocê é o responsável por estes deals. Trabalhe-os em ordem: use suas "
        "ferramentas para contatar, registrar e mover o stage no CRM. Não pergunte "
        "o que fazer — a fila é a sua agenda do dia. Se um deal não precisar de "
        "ação, registre o motivo e siga. Ao terminar, o stage e o next_follow_up "
        "ficam registrados no CRM e a próxima fila é derivada deles."
    )