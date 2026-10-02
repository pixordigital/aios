"""Cross-team collaboration + owner notification tools for managers.

Two tools, one module (they share the org-scoping and Slack resolution):

- ``ask_team_manager`` — a manager (or an orchestrator) hands a request to
  another team's manager and gets the reply inline. Thread is persisted as a
  ``Conversation`` owned by the *target* team with the requester recorded in
  ``extra_data["collab"]``, so both sides have an audit trail and no new table
  is needed.
- ``notify_human`` — a manager messages the org owner on Slack on demand, not
  only on the scheduled report cadence.

Both refuse to act without a resolved ``_org_id``. ToolEngine sets it from the
running agent; an unknown caller is not allowed to reach across teams, because
every lookup here is by name/id and a name is guessable.
"""

import logging
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

# ask_team_manager runs the target manager agent inline. Without a hop ceiling
# two managers can hand the same question back and forth forever inside one
# ARQ job. ponytail: fixed 3 hops; make it per-org config if real chains appear.
_MAX_HOPS = 3
_hops: ContextVar[int] = ContextVar("collab_hops", default=0)

CONVERSATION_CHANNEL = "internal"


def _require_org(org_id: str) -> str:
    if not org_id:
        raise PermissionError(
            "team collaboration needs a resolved org; run this tool from an agent."
        )
    return org_id


async def _resolve_team(sess, org_id: str, ref: str):
    """Find a team by id or (case-insensitive) name inside one org."""
    from sqlalchemy import or_, select

    from aios.db.models import Team

    ref = (ref or "").strip()
    if not ref:
        return None
    stmt = select(Team).where(
        Team.org_id == org_id,
        or_(Team.id == ref, Team.name.ilike(ref)),
    )
    return (await sess.execute(stmt.limit(2))).scalars().first()


async def _caller_team(sess, org_id: str, from_team: str, caller_agent_id: str):
    """Caller identity: explicit from_team, else the team the caller is on."""
    from sqlalchemy import select

    from aios.db.models import Team, team_agents

    if from_team and from_team.strip():
        return await _resolve_team(sess, org_id, from_team)
    if not caller_agent_id:
        return None
    return (await sess.execute(
        select(Team).join(team_agents, team_agents.c.team_id == Team.id)
        .where(Team.org_id == org_id, team_agents.c.agent_id == caller_agent_id)
        .limit(1)
    )).scalars().first()


async def _collab_thread(sess, *, org_id: str, to_team, from_team, manager):
    """Find or create the durable requester↔manager thread for a team pair."""
    from sqlalchemy import select

    from aios.db.models import Conversation

    key = f"collab:{from_team.id}->{to_team.id}"
    conv = (await sess.execute(
        select(Conversation).where(
            Conversation.org_id == org_id,
            Conversation.external_id == key,
        )
    )).scalars().first()
    if conv:
        return conv
    conv = Conversation(
        org_id=org_id,
        channel=CONVERSATION_CHANNEL,
        external_id=key,
        team_id=to_team.id,
        agent_id=manager.id,
        extra_data={
            "collab": {
                "from_team_id": from_team.id,
                "from_team_name": from_team.name,
                "to_team_id": to_team.id,
                "to_team_name": to_team.name,
                "manager_agent_id": manager.id,
            }
        },
    )
    sess.add(conv)
    await sess.commit()
    await sess.refresh(conv)
    return conv


class AskTeamManagerInput(BaseModel):
    to_team: str = Field(description="Nome ou id do time que voce precisa acionar")
    question: str = Field(description="O que precisa desse time, em uma frase")
    context: str = Field(default="", description="Contexto extra: o que ja foi tentado, prazo")
    from_team: str = Field(
        default="",
        description="Seu time. Opcional — inferido do agente que esta rodando.",
    )


class AskTeamManagerTool(BaseTool):
    name = "ask_team_manager"
    description = (
        "Pede ajuda/colaboração para o gerente de OUTRO time da mesma org e "
        "recebe a resposta na hora. Use quando o bloqueio precisa de outro time "
        "(ex.: pedir ao gerente de dev para revisar uma migration). Nao use para "
        "seu proprio time — delegue internamente."
    )
    input_model = AskTeamManagerInput

    async def run(
        self,
        to_team: str,
        question: str,
        context: str = "",
        from_team: str = "",
    ) -> dict[str, Any]:
        from aios.db.engine import async_session
        from aios.db.models import Agent, Message

        org_id = _require_org(self._org_id)
        if not (question or "").strip():
            return {"ok": False, "error": "question is required"}

        depth = _hops.get()
        if depth >= _MAX_HOPS:
            return {
                "ok": False,
                "error": f"collaboration hop limit reached ({_MAX_HOPS}); "
                "escalate to a human instead of bouncing between managers",
            }

        async with async_session() as sess:
            target = await _resolve_team(sess, org_id, to_team)
            if target is None:
                return {"ok": False, "error": f"team not found in this org: {to_team!r}"}
            if not target.manager_agent_id:
                return {
                    "ok": False,
                    "error": f"team {target.name!r} has no manager agent to ask",
                }
            caller = await _caller_team(sess, org_id, from_team, self._agent_id)
            if caller is None:
                return {
                    "ok": False,
                    "error": "could not resolve your own team; pass from_team explicitly",
                }
            if caller.id == target.id:
                return {
                    "ok": False,
                    "error": f"{target.name!r} is your own team — delegate internally "
                    "instead of asking your own manager",
                }

            manager = await sess.get(Agent, target.manager_agent_id)
            if manager is None:
                return {"ok": False, "error": f"manager agent missing for {target.name!r}"}

            conv = await _collab_thread(
                sess, org_id=org_id, to_team=target, from_team=caller, manager=manager
            )
            request = question.strip()
            if (context or "").strip():
                request = f"{request}\n\nContexto:\n{context.strip()}"

            sess.add(Message(
                conversation_id=conv.id,
                org_id=org_id,
                role="user",
                content=request,
                extra_data={
                    "collab": True,
                    "from_team_id": caller.id,
                    "from_team_name": caller.name,
                    "direction": "request",
                },
            ))
            await sess.commit()
            conv_id = conv.id

        prompt = (
            f"O gerente do time {caller.name!r} abriu uma collaboracao com "
            f"seu time ({target.name!r}). Responda direto: o que voce precisa, "
            f"o que assume, e em que prazo.\n\nPedido:\n{request}"
        )

        from aios.core.orchestrator import _get_runtime

        token = _hops.set(depth + 1)
        try:
            reply = await _get_runtime(manager, None).run(conv_id, prompt)
        except Exception:
            logger.exception("ask_team_manager: manager %s failed", manager.id)
            return {
                "ok": False,
                "error": f"manager {manager.name!r} did not answer; thread kept for retry",
                "conversation_id": conv_id,
            }
        finally:
            _hops.reset(token)

        reply = (reply or "").strip()
        # A failed run returns a reflection/HITL string, not an answer. Telling
        # the caller "ok, here's what your colleague said" would be a lie.
        from aios.core.agent import is_failed_run

        if is_failed_run(reply):
            return {
                "ok": False,
                "error": f"manager {manager.name!r} could not answer; thread kept "
                "so the request can be retried",
                "conversation_id": conv_id,
            }

        async with async_session() as sess:
            sess.add(Message(
                conversation_id=conv_id,
                org_id=org_id,
                role="assistant",
                content=reply,
                agent_id=manager.id,
                extra_data={"collab": True, "direction": "reply"},
            ))
            await sess.commit()

        return {
            "ok": True,
            "team": target.name,
            "manager": manager.name,
            "reply": reply[:4000],
            "conversation_id": conv_id,
        }


class NotifyHumanInput(BaseModel):
    message: str = Field(description="O que o dono precisa saber. Curto e com o pedido/dpra")
    urgency: str = Field(default="info", description="info | warning | blocker")
    team: str = Field(default="", description="Assina com o time. Opcional.")


class NotifyHumanTool(BaseTool):
    name = "notify_human"
    description = (
        "Manda mensagem para o dono da empresa no Slack, na hora. Use para o que "
        "ele precisa saber AGORA: blocker que trava o time, meta quebrada, decisao "
        "de negocio. Nao use para status rotina — o relatorio semanal ja cobre. "
        "Se o time estiver atrasado da meta, use urgency=warning."
    )
    input_model = NotifyHumanInput

    async def run(self, message: str, urgency: str = "info", team: str = "") -> dict[str, Any]:
        import asyncio

        from aios.core.meetings import human_slack_targets, post_to_slack
        from aios.db.engine import async_session

        org_id = _require_org(self._org_id)
        text = (message or "").strip()
        if not text:
            return {"ok": False, "error": "message is required"}

        # ToolEngine passes LLM args through without running input_model, so a
        # literal null here is reachable and .strip() on it would raise.
        team_name = (team or "").strip()
        if not team_name and self._agent_id:
            # Sign the message with the caller's own team, and target that
            # team's DM — an org-wide send would reach every manager's DM.
            async with async_session() as sess:
                caller = await _caller_team(sess, org_id, "", self._agent_id)
            if caller is not None:
                team_name = caller.name

        targets = await human_slack_targets(
            org_id, team_id=(await _team_id(org_id, team_name)) if team_name else ""
        )
        if not targets:
            return {
                "ok": False,
                "error": (
                    f"no Slack DM wired for the owner"
                    f"{f' ({team_name})' if team_name else ''}; set one via "
                    "/dashboard/channels with config.slack_1on1 = true"
                ),
            }

        icons = {
            "info": ":information_source:",
            "warning": ":warning:",
            "blocker": ":rotating_light:",
        }
        icon = icons.get(urgency, icons["info"])
        header = f"{icon} *{(urgency or 'info').upper()}*"
        if team_name:
            header += f" — {team_name}"
        body = f"{header}\n\n{text}"

        # post_to_slack is sync urllib — keep it off the event loop.
        sent = [
            t for t in targets
            if await asyncio.to_thread(post_to_slack, t["token"], t["channel"], body)
        ]
        return {
            "ok": bool(sent),
            "delivered": len(sent),
            "attempted": len(targets),
            "channels": [t["channel"] for t in sent],
        }


async def _team_id(org_id: str, name: str) -> str | None:
    from aios.db.engine import async_session

    async with async_session() as sess:
        team = await _resolve_team(sess, org_id, name)
        return team.id if team else None


TOOL_REGISTRY["ask_team_manager"] = {
    "code_reference": "aios.tools.team_collaboration.AskTeamManagerTool"
}
TOOL_REGISTRY["notify_human"] = {
    "code_reference": "aios.tools.team_collaboration.NotifyHumanTool"
}