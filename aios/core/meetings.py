"""Weekly team standups + biweekly manager 1:1s posted to Slack.

Transport is stdlib urllib (no new deps). Jobs run daily 9h via ARQ cron
and self-skip unless Monday (standup) / even-ISO-week Monday (1:1).
"""

import json
import logging
import urllib.request

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


async def team_week_stats(db, org_id: str, team_id: str) -> dict:
    """Conversations/messages/deals-closed in last 7d for a team."""
    from datetime import datetime, timedelta

    from sqlalchemy import func, select

    from aios.db.models import Conversation, CrmDeal, Message

    week_ago = datetime.utcnow() - timedelta(days=7)
    conv_ids = (await db.execute(select(Conversation.id).where(
        Conversation.org_id == org_id,
        Conversation.team_id == team_id,
        Conversation.created_at >= week_ago,
    ))).scalars().all()
    msgs = 0
    if conv_ids:
        msgs = (await db.execute(select(func.count(Message.id)).where(
            Message.conversation_id.in_(conv_ids),
            Message.created_at >= week_ago,
        ))).scalar() or 0
    won = (await db.execute(select(func.coalesce(func.sum(CrmDeal.value), 0)).where(
        CrmDeal.org_id == org_id,
        CrmDeal.team_id == team_id,
        CrmDeal.stage == "closed_won",
        CrmDeal.updated_at >= week_ago,
    ))).scalar() or 0
    return {"conversations": len(conv_ids), "messages": msgs, "won_7d_brl": round(won, 2)}


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


def one_on_one_text(team_name: str, manager_name: str, stats: dict, goal: dict | None) -> str:
    lines = [
        f":handshake: *1:1 — {manager_name} ({team_name})*",
        f"Semana: {stats['conversations']} conversas, {stats['messages']} msgs, R${stats['won_7d_brl']:.2f} ganhos.",
    ]
    if goal and goal.get("target_brl"):
        lines.append(f"Meta: {goal['pct']}% (R${goal['won_brl']:.2f}/{goal['target_brl']:.2f}), status {goal['status']}.")
    lines += [
        "1. Progresso desde ultimo 1:1?",
        "2. Maior struggle do time?",
        "3. Um ajuste pra proxima quinzena?",
        "Responde aqui — vira tarefa do time se precisar.",
    ]
    return "\n".join(lines)
