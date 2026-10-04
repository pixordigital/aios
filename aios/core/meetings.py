"""Team standups, manager 1:1s and goal reports posted to Slack.

Transport is stdlib urllib (no new deps). Jobs run daily via ARQ cron and
self-skip unless the right day (standup + 1:1 on Monday, monthly on the 1st).

A team reaches the owner through a ChannelConnection whose config carries
``slack_1on1: true`` — that is the DM channel for reports and ``notify_human``.
When a team has no such connection, reports fall back to the team channel so a
report is never silently dropped.
"""

import json
import logging
import urllib.request

from sqlalchemy import select

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api/chat.postMessage"


def post_to_slack(bot_token: str, channel: str, text: str) -> bool:
    """Post a message via Slack Web API. Returns True on ok."""
    if not bot_token or not channel:
        return False
    if bot_token.startswith("enc:"):
        try:
            from aios.core.secrets import decrypt_channel_config
            bot_token = decrypt_channel_config({"t": bot_token})["t"]
        except Exception:
            logger.warning("meetings: cannot decrypt slack token")
            return False
    req = urllib.request.Request(
        SLACK_API,
        data=json.dumps({"channel": channel, "text": text}).encode(),
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get("ok", False)
    except Exception:
        logger.exception("meetings: slack post failed")
        return False


async def team_stats(db, org_id: str, team_id: str, days: int = 7,
                     since=None, until=None) -> dict:
    """Conversations/messages/deals-closed in a window for a team.

    `since`/`until` are explicit datetimes for a real calendar window (the
    monthly report covers the previous calendar month, not "last 31 days").
    `days` is the fallback when no window is given.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from aios.db.models import Conversation, CrmDeal, Message

    if since is None:
        since = datetime.utcnow() - timedelta(days=days)
    # `until` is exclusive so consecutive calendar windows never double-count.
    end = until or datetime.utcnow()

    conv_ids = (await db.execute(select(Conversation.id).where(
        Conversation.org_id == org_id,
        Conversation.team_id == team_id,
        Conversation.created_at >= since,
        Conversation.created_at < end,
    ))).scalars().all()
    msgs = 0
    if conv_ids:
        msgs = (await db.execute(select(func.count(Message.id)).where(
            Message.conversation_id.in_(conv_ids),
            Message.created_at >= since,
            Message.created_at < end,
        ))).scalar() or 0
    won = (await db.execute(select(func.coalesce(func.sum(CrmDeal.value), 0)).where(
        CrmDeal.org_id == org_id,
        CrmDeal.team_id == team_id,
        CrmDeal.stage == "closed_won",
        CrmDeal.updated_at >= since,
        CrmDeal.updated_at < end,
    ))).scalar() or 0
    return {
        "days": days,
        "since": since.isoformat(),
        "until": end.isoformat(),
        "conversations": len(conv_ids),
        "messages": msgs,
        "won_brl": round(won, 2),
        # Kept for the existing standup/1:1 templates, which read won_7d_brl.
        "won_7d_brl": round(won, 2),
    }


async def team_week_stats(db, org_id: str, team_id: str) -> dict:
    return await team_stats(db, org_id, team_id, days=7)


def standup_text(team_name: str, manager_name: str, stats: dict, goal: dict | None) -> str:
    lines = [
        f":bar_chart: *Weekly — {team_name}* (manager: {manager_name})",
        f"Conversas: {stats['conversations']} | Msgs: {stats['messages']} | Ganho 7d: R${stats['won_7d_brl']:.2f}",
    ]
    if goal and goal.get("target_brl"):
        lines.append(
            f"Meta {goal['year_month']}: R${goal['won_brl']:.2f} / R${goal['target_brl']:.2f} "
            f"({goal['pct']}%, esperado R${goal['expected_brl']:.2f}) — {goal['status']}. "
            f"Projecao: R${goal['projected_brl']:.2f}"
        )
    lines += ["Struggles? Ajustes? Responde nesta thread.", "Gerado pelo AIOS."]
    return "\n".join(lines)


# ── Slack target resolution ──────────────────────────────────────────────

def _target_of(conn) -> dict | None:
    cfg = conn.config if isinstance(conn.config, dict) else {}
    channel, token = cfg.get("slack_channel_id", ""), cfg.get("bot_token", "")
    if not channel or not token:
        return None
    return {
        "conn_id": conn.id,
        "token": token,
        "channel": channel,
        "team_id": getattr(conn, "team_id", None),
        "is_1on1": bool(cfg.get("slack_1on1")),
    }


def report_targets(conns, team_id: str) -> list[dict]:
    """Where a team reports to the owner: its DM connection, else team channel.

    `conns` are the org's active slack connections. Returning the team channel
    as fallback is deliberate — a report with nowhere to go is worse than one
    in the wrong room.
    """
    mine = [t for t in (_target_of(c) for c in conns if getattr(c, "team_id", None) == team_id) if t is not None]
    dm = [t for t in mine if t["is_1on1"]]
    room = [t for t in mine if not t["is_1on1"]]
    return dm or room


async def human_slack_targets(org_id: str, team_id: str = "") -> list[dict]:
    """Owner DM connections for an org, optionally narrowed to one team.

    DM-only by design: `notify_human` carries things the owner must not miss,
    and a team room is not a delivery channel for those. Scheduled reports use
    `report_targets`, which does fall back to the team channel.
    """
    from sqlalchemy import select

    from aios.db.backend import db_session
    from aios.db.models import ChannelConnection

    async with db_session() as db:
        stmt = select(ChannelConnection).where(
            ChannelConnection.org_id == org_id,
            ChannelConnection.channel_type == "slack",
            ChannelConnection.is_active == True,  # noqa: E712
        )
        if team_id:
            stmt = stmt.where(ChannelConnection.team_id == team_id)
        conns = (await db.execute(stmt)).scalars().all()
        return [t for t in (_target_of(c) for c in conns) if t and t["is_1on1"]]


# ── Reports ──────────────────────────────────────────────────────────────

_REPORT_PROMPT = """Voce e o gerente do time "{team}". Escreva a atualizacao pro dono da empresa.

Numeros (ja apurados, nao recalcule):
{stats}
Meta {month}: {goal}

Responda em ate 120 palavras, texto simples, sem tabela e sem cabecalho markdown. Cubra nesta ordem:
1. como o time foi na janela;
2. o que voce fez de concreto;
3. se a meta esta em risco: o que voce vai mudar, e ate quando.

Se a meta estiver em dia, diga isso e o que voce quer preservar. Nao invente numero que nao esta
acima — se nao tem dado para alguma coisa, escreva "sem dado".
"""


async def _report_conversation(db, org_id: str, team, manager, kind: str) -> str:
    """One reused thread per (team, kind) so the manager keeps report history."""
    from aios.db.models import Conversation

    key = f"report:{team.id}:{kind}"
    conv = (await db.execute(
        select(Conversation).where(
            Conversation.org_id == org_id,
            Conversation.external_id == key,
        )
    )).scalars().first()
    if conv:
        return conv.id
    conv = Conversation(
        org_id=org_id,
        channel="internal",
        external_id=key,
        team_id=team.id,
        agent_id=manager.id,
        extra_data={"report": {"kind": kind, "team_id": team.id}},
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv.id


async def manager_narrative(manager, team, stats: dict, goal: dict | None,
                            kind: str) -> str:
    """Ask the manager agent to narrate its own numbers. '' if it can't.

    Returns '' rather than a template when the agent is unreachable, so the
    report says the manager didn't answer instead of inventing one.
    """
    if manager is None or team is None:
        return ""
    from aios.core.orchestrator import _get_runtime

    goal_txt = "sem meta cadastrada"
    if goal and goal.get("target_brl"):
        goal_txt = (
            f"R${goal['won_brl']:.2f} de R${goal['target_brl']:.2f} ({goal['pct']}%), "
            f"esperado R${goal['expected_brl']:.2f} no dia {goal['day']}, "
            f"status {goal['status']}, projecao R${goal['projected_brl']:.2f}"
        )
    window = "ultimos 7 dias" if kind == "weekly" else "o mes fechado"
    prompt = _REPORT_PROMPT.format(
        team=team.name,
        stats=(
            f"Janela: {window}. Conversas: {stats['conversations']}, "
            f"mensagens: {stats['messages']}, ganho: R${stats['won_brl']:.2f}"
        ),
        month=(goal or {}).get("year_month", "n/a"),
        goal=goal_txt,
    )

    from aios.db.backend import db_session
    from aios.db.models import Message

    try:
        async with db_session() as db:
            conv_id = await _report_conversation(
                db, manager.org_id, team=team, manager=manager, kind=kind
            )
        reply = await _get_runtime(manager, None).run(conv_id, prompt)
        text = (reply or "").strip()
        # A failed run returns a reflection/HITL string, not an answer. Publishing
        # that as the team's report would be worse than publishing nothing.
        from aios.core.agent import is_failed_run

        if is_failed_run(text):
            return ""
        async with db_session() as db:
            db.add(Message(
                conversation_id=conv_id, org_id=manager.org_id, role="assistant",
                content=text, agent_id=manager.id,
            ))
            await db.commit()
        return text
    except Exception:
        logger.exception("manager_narrative: manager %s failed", manager.id)
        return ""


_STATUS_PT = {
    "ahead": "na frente",
    "behind": "atrasado",
    "no_goal": "sem meta",
    "not_started": "mes ainda nao comecou",
}


def _goal_block(goal: dict | None) -> list[str]:
    if not goal or not goal.get("target_brl"):
        return ["*Meta* — sem meta cadastrada para este periodo."]
    assert goal is not None
    # str() once: goal is an untyped dict from the sales layer, so every .get
    # is Any and the status lookup below would not narrow.
    status = str(goal.get("status") or "")
    return [
        f"*Meta {goal['year_month']}*",
        (
            f"R${goal['won_brl']:.2f} de R${goal['target_brl']:.2f} ({goal['pct']}%) · "
            f"esperado R${goal['expected_brl']:.2f} · {goal['deals_won']} negocio(s) · "
            f"status *{_STATUS_PT.get(status, status)}*"
        ),
        f"Projecao: R${goal['projected_brl']:.2f} · falta R${goal['remaining_brl']:.2f}",
    ]


def report_text(kind: str, team_name: str, manager_name: str, stats: dict,
                goal: dict | None, narrative: str) -> str:
    """Compose the Slack report: numbers, goal status, manager's own plan.

    The action plan is the manager's words, never a generated default — if the
    manager did not answer, the report says so instead of implying a plan
    exists.
    """
    title = "Relatorio Semanal" if kind == "weekly" else "Relatorio Mensal"
    icon = ":bar_chart:" if kind == "weekly" else ":calendar:"
    window = f"ultimos {stats.get('days', 7)} dias" if kind == "weekly" else "mes fechado"

    lines = [
        f"{icon} *{title} — {team_name}* · gerente: {manager_name}",
        f"Janela: {window}",
        "",
        "*Numeros*",
        (
            f"Conversas: {stats['conversations']} · mensagens: {stats['messages']} · "
            f"ganho: R${stats['won_brl']:.2f}"
        ),
        "",
        *_goal_block(goal),
        "",
    ]

    behind = bool(goal and goal.get("status") == "behind")
    if narrative:
        lines += ["*Leitura do gerente*", narrative, ""]
        if behind:
            lines += [
                (
                    "*Meta atrasada* — plano de recuperacao acima, do proprio gerente. "
                    "Se nao fechar o plano aqui, ajuste com ele nesta thread."
                ),
                "",
            ]
    else:
        lines += [
            (
                "*Leitura do gerente* — o gerente nao respondeu nesta rodada. "
                "Os numeros acima sao o registro; o plano de acao nao foi reportado."
            ),
            "",
        ]

    if kind == "weekly":
        lines += [
            "*Pauta da nossa 1:1*",
            "1. O time esta no caminho certo, ou o plano precisa mudar?",
            "2. Precisa de mim em algo especifico (pessoa, dinheiro, prioridade)?",
            "3. Algum ajuste de meta, escopo ou processo?",
        ]
    lines += ["Responda nesta thread — vira tarefa do time se precisar.", "Gerado pelo AIOS."]
    return "\n".join(lines)
