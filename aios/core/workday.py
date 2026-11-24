"""The daily board an agent works, built from state it already owns.

An employee clocks in and knows what is on their plate because the work is
tracked somewhere durable. Agents had no equivalent: `signals.rank_queue` built
a "fila do dia" for the dashboard and for an API, and no agent ever worked it.

So the board is not a new table. It is durable work the agent can pull: open
CRM deals it owns and open OCP tasks it owns or that belong to its department,
ranked by the timing score that already existed. CRM/OCP state *is* the memory:
yesterday's work shows up as a moved stage, a refreshed `last_contacted_at`, a
pushed `next_follow_up`, or a task status change, so tomorrow's board is
different without anything having to remember it.

SDR and support are excluded on purpose. They are reactive: they act when a
message arrives, and their work arrives as events rather than being pulled from
a board. Putting them on a daily queue would have them prospecting deals that
already have a live conversation open.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import and_, or_, select

from aios.core.signals import OPEN_STAGES, rank_queue

# Agents whose day is driven by inbound traffic, not by a board they pull.
REACTIVE_AGENT_TYPES = frozenset({"sdr", "support"})

DEFAULT_BOARD_SIZE = 10

# OCP tasks with a terminal status are not work. Everything else is open.
CLOSED_TASK_STATUSES = ("completed", "cancelled")

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


def _task_due(task, now: datetime) -> str | None:
    """An OCP task deadline that has passed, as an ISO timestamp."""
    due = task.deadline
    if not due:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due.isoformat() if due <= now else None


async def board_for_agent(agent, db, limit: int = DEFAULT_BOARD_SIZE) -> dict:
    """The agent's board for today: open deals and OCP tasks, best first.

    Due follow-ups and deadlines are lifted to the front regardless of timing
    score. A promise made today outranks a hotter lead that happens to score
    higher; burying it under a score sort is how a promise gets missed.
    """
    now = datetime.now(timezone.utc)
    from aios.db.models import CrmDeal
    from aios.governance.ocp import DepartmentMember, SharedTask

    rows = (
        await db.execute(
            select(CrmDeal).where(
                CrmDeal.org_id == agent.org_id,
                CrmDeal.agent_id == agent.id,
                CrmDeal.stage.in_(OPEN_STAGES),
            )
        )
    ).scalars().all()

    # OCP has no team-owned task field: a task reaches a team through the
    # responsible department, with membership held in department_members.
    dept_ids = (
        await db.execute(
            select(DepartmentMember.department_id).where(
                DepartmentMember.org_id == agent.org_id,
                DepartmentMember.member_type == "agent",
                DepartmentMember.agent_id == agent.id,
                DepartmentMember.is_active.is_(True),
            )
        )
    ).scalars().all()
    tasks = (
        await db.execute(
            select(SharedTask).where(
                SharedTask.org_id == agent.org_id,
                SharedTask.status.not_in(CLOSED_TASK_STATUSES),
                or_(
                    and_(SharedTask.owner_type == "agent", SharedTask.owner_id == agent.id),
                    SharedTask.responsible_department_id.in_(dept_ids),
                ),
            )
        )
    ).scalars().all()
    # A task can match both owner and department; it is one item of work.
    tasks = list({t.id: t for t in tasks}.values())

    # Adapt tasks to the shape rank_queue already scores, so both sources share
    # one ranking without a second scoring rule. Deals stay ahead on ties.
    stubs = [
        SimpleNamespace(
            id=t.id, stage="opportunity", source="task", value=0,
            updated_at=t.updated_at, extra_data={}, _task=t,
        )
        for t in tasks
    ]
    ranked = rank_queue(list(rows) + stubs, limit=limit, now=now)

    items = []
    for r in ranked:
        row = r["deal"]
        task = getattr(row, "_task", None)
        if task is not None:
            items.append(
                {
                    "source": "task",
                    "task_id": task.id,
                    "lead": task.title,
                    "title": task.title,
                    "status": task.status,
                    "priority": task.priority,
                    "timing": r["timing"],
                    "why": r["reasons"],
                    "hours_since_touch": r["hours_since_touch"],
                    "objective": task.objective or "",
                    "expected_deliverable": task.expected_deliverable or "",
                    "deadline": task.deadline.isoformat() if task.deadline else "",
                    "due_overdue": _task_due(task, now),
                }
            )
            continue
        deal = row
        ex = deal.extra_data or {}
        items.append(
            {
                "source": "crm",
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

    # Due-today first, then keep the timing order within each group. Explicit
    # ref tie-break keeps identical scores stable across DB row order; deals win
    # a tie so adding a task cannot change the order of an existing CRM board.
    items.sort(
        key=lambda i: (
            i["due_overdue"] is None,
            -i["timing"],
            i["source"] == "task",
            i.get("task_id") or i["deal_id"],
        )
    )

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
    has_tasks = False
    for i, it in enumerate(board["items"], 1):
        if it.get("source") == "task":
            has_tasks = True
            bits = [f"status={it['status']}", f"prioridade={it['priority']}"]
            if it["due_overdue"]:
                bits.append(f"PRAZO VENCIDO em {it['due_overdue']}")
            elif it["deadline"]:
                bits.append(f"prazo {it['deadline']}")
            if it["hours_since_touch"] is not None:
                bits.append(f"{it['hours_since_touch']}h sem toque")
            rows.append(
                f"{i}. source=task | task_id={it['task_id']} | "
                f"{it.get('title') or it.get('lead') or it['task_id']} | {' | '.join(bits)}"
                + (f"\n   objetivo: {it['objective']}" if it["objective"] else "")
                + (f"\n   entregável: {it['expected_deliverable']}" if it["expected_deliverable"] else "")
            )
            continue
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

    tail = (
        "\n\nVocê é o responsável por estes deals. Trabalhe-os em ordem: use suas "
        "ferramentas para contatar, registrar e mover o stage no CRM. Não pergunte "
        "o que fazer — a fila é a sua agenda do dia. Se um deal não precisar de "
        "ação, registre o motivo e siga. Ao terminar, o stage e o next_follow_up "
        "ficam registrados no CRM e a próxima fila é derivada deles."
    )
    if has_tasks:
        tail = (
            "\n\nItens deal_id são deals do CRM; itens source=task são tarefas do OCP. "
            "Trabalhe tudo em ordem: para deals, contate, registre e mova o stage no "
            "CRM; para tarefas, entregue o resultado e registre a transição de status "
            "no OCP. Não pergunte o que fazer — a fila é a sua agenda do dia. Se um "
            "item não precisar de ação, registre o motivo e siga. Ao terminar, o "
            "estado de cada item fica registrado na ferramenta de origem e a próxima "
            "fila é derivada dele."
        )

    return head + "\n".join(rows) + tail
