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
import re
from contextvars import ContextVar
from types import SimpleNamespace
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


async def _caller_agent(sess, org_id: str, caller_agent_id: str):
    """The running agent, but only inside this org."""
    from sqlalchemy import select

    from aios.db.models import Agent

    if not caller_agent_id:
        return None
    return (await sess.execute(
        select(Agent).where(Agent.id == caller_agent_id, Agent.org_id == org_id)
    )).scalars().first()


def _is_org_coordinator(agent) -> bool:
    """The bootstrap-marked coordinator is teamless on purpose."""
    from aios.core.org_bootstrap import ORCHESTRATOR_MARKER

    return bool(agent) and (agent.extra_data or {}).get("business_setup") == ORCHESTRATOR_MARKER


async def _agent_on_team(sess, team_id: str, agent_id: str) -> bool:
    from sqlalchemy import select

    from aios.db.models import team_agents

    if not agent_id:
        return False
    row = (await sess.execute(
        select(team_agents.c.agent_id).where(
            team_agents.c.team_id == team_id,
            team_agents.c.agent_id == agent_id,
        ).limit(1)
    )).first()
    return row is not None


async def _caller_team(
    sess, org_id: str, from_team: str, caller_agent_id: str, *, org_scoped: bool = False
):
    """Return (caller, error). Explicit from_team is caller-reported, so verify it."""
    from sqlalchemy import select

    from aios.db.models import Team, team_agents

    agent = await _caller_agent(sess, org_id, caller_agent_id)
    coordinator = org_scoped and _is_org_coordinator(agent)

    if from_team and from_team.strip():
        team = await _resolve_team(sess, org_id, from_team)
        if team is None:
            return None, f"from_team not found in this org: {from_team!r}"
        if not coordinator and not await _agent_on_team(sess, team.id, caller_agent_id):
            return None, f"from_team {from_team!r} is not your team"
        return team, None

    if coordinator:
        # Only the audit metadata and thread key use this id; Conversation.team_id
        # is the *target* team, so no fake FK is ever written.
        return SimpleNamespace(id=f"org:{org_id}", name=agent.name or "coordenacao geral"), None

    if not caller_agent_id:
        return None, "could not resolve your own team; pass from_team explicitly"
    team = (await sess.execute(
        select(Team).join(team_agents, team_agents.c.team_id == Team.id)
        .where(Team.org_id == org_id, team_agents.c.agent_id == caller_agent_id)
        .limit(1)
    )).scalars().first()
    if team is None:
        return None, "could not resolve your own team; pass from_team explicitly"
    return team, None


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
            caller, error = await _caller_team(
                sess, org_id, from_team, self._agent_id, org_scoped=True
            )
            if caller is None:
                return {"ok": False, "error": error}
            if caller.id == target.id:
                return {
                    "ok": False,
                    "error": f"{target.name!r} is your own team — delegate internally "
                    "instead of asking your own manager",
                }

            # The bypass guard. Asking another team to *build* something is a
            # decision, not a question, and it has to reach the owner with both
            # sides on it. ask_team_manager cannot guarantee that, so it hands
            # build-shaped asks over instead of quietly delivering them.
            # Default-deny for teams that can build: refuse unless the ask is
            # recognisably informational, on top of the keyword guard. Both
            # layers are heuristics, so this is defence in depth around
            # request_build rather than a proof -- but it means an oblique
            # phrasing now fails closed instead of open.
            if _looks_like_build_request(question) or (
                _is_build_capable(getattr(target, "name", ""))
                and not _looks_like_information_request(question)
            ):
                return {
                    "ok": False,
                    "error": (
                        "that reads as a build request, not a question. "
                        "Use `request_build` instead: it requires the revenue "
                        "justification, collects the other manager's feasibility "
                        "analysis, and notifies the owner. Going around it is how "
                        "a build reaches dev without the owner ever hearing."
                    ),
                    "suggested_tool": "request_build",
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
        from aios.core.meetings import human_slack_targets
        from aios.core.owner_notify import deliver_owner
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
                caller, _ = await _caller_team(sess, org_id, "", self._agent_id)
            if caller is not None:
                team_name = caller.name

        resolved_team_id = await _team_id(org_id, team_name) if team_name else None
        targets = await human_slack_targets(org_id, team_id=resolved_team_id or "")
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

        return await deliver_owner(
            org_id, body, urgency=urgency or "info", requires_ack=True,
            team_id=resolved_team_id or "",
        )


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

# ─── the one path that must always reach a human ───────────────────────────
#
# A manager asking another team to build something is a decision with a cost and
# a revenue claim attached, so the owner is always told. `ask_team_manager` plus
# `notify_human` could express that in prompt text, but prompt text is advice:
# nothing stopped a sales manager from quietly asking dev and never mentioning
# it. This makes the sequence the only way through, and it fails closed twice:
#
#   1. no factual justification -> refuse before anyone is contacted, so the
#      owner is never asked to judge a vague "this would help sales";
#   2. the Slack post fails -> the request fails. A build request that reached
#      dev but not the owner is exactly the outcome the owner must never miss.

# A justification with no number in it is a wish, not evidence. These are the
# shapes a real revenue/process claim arrives in: R$ amounts, percentages,
# multiples ("2x"), or an explicit reference to a metric that exists.
_METRIC_HINTS = (
    "r$", "us$", "%", "x", "mrr", "arr", "ticket", "conversão", "conversao",
    "cac", "l tv", "ltv", "churn", "pipeline", "forecast", "meta", "receita",
    "faturamento", "upsell", "win rate", "agenda", "agendamento",
)


# Commands work, as opposed to asking for information. `ask_team_manager` is a
# question tool; "build me X" is a decision tool, and the owner's rule is that
# both managers and the owner see it. So a build-shaped cross-team ask is
# refused here and pointed at request_build, which enforces the notification.
#
# Honest limit: this is a keyword guard, not a proof. It routes obvious
# build-shaped asks into the enforced door and lets genuine questions through,
# and a sufficiently oblique phrasing would still get through. It closes the
# easy bypass; it does not make the informal path impossible.

# Stems, matched against accent-stripped lowercase. Stems rather than words,
# because Portuguese runs the endings off the stem ("construir", "construa",
# "construem") and an exact-word list misses the imperative that matters most.
# Verbs only. Bare nouns were tried and removed: "qual o endpoint que voces
# usam?" is a question about infrastructure that exists, and routing it into
# request_build would ping the owner about trivia every time someone looked
# something up.
_BUILD_STEMS = (
    "constru", "implement", "adicion", "arrum", "arranj", "desenvolv",
    "codific", "automatiz", "refator", "integr", "criar", "cria",
    # "montar" was missing, and "voces conseguem me ajudar a montar uma tela de
    # checkout?" is the most natural phrasing of the bypass this guards.
    # "mont" covers montar/monta/montem/montar.
    "mont", "precisamos de", "precisa de", "precisar de",
    "e que tal", "vamos fazer", "tem como fazer",
)

# Inquiries that merely NAME a build word. Same suppression as _PAST_REF: the
# ask is for information about work, not for the work itself.
_QUESTION_FRAMES = (
    "status", "situacao", "andamento", "progresso", "como esta", "como vai",
    "como estao", "qual o", "qual a", "me passar", "tem pronto", "ja ficou",
    "funcionando", "funciona", "document",
)

# References to work that already exists. "como está a integração que vocês
# construíram?" mentions a build verb but asks for information, and routing
# that into request_build would spam the owner every time someone checked on a
# past change.
_PAST_REF = (
    "construiram", "construiu", "construida", "construido", "construcao",
    "implementaram", "implementou", "implementada", "implementado",
    "feito", "feita", "existente", "ja foi", "ja existe", "rodando",
    "criaram", "criou", "criamos", "usam", "usando", "usado",
)


def _fold(text: str) -> str:
    """Lowercase and strip accents.

    Without this "construí" and "construir" collide on a shared substring, so a
    past-tense reference to past work reads as a request to build something.
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", stripped)


# Teams that can be asked to BUILD. For these, ask_team_manager is
# default-deny: anything that is not clearly an information request is refused
# and pointed at request_build. A keyword denylist alone was never a boundary --
# "voces conseguem me ajudar a montar uma tela de checkout?" carries no stem
# from _BUILD_STEMS and walked straight through.
_BUILD_CAPABLE_TEAMS = ("dev", "devops", "engineering", "tecnologia", "ti")

# Markers of an information request. Deliberately generous: the cost of a false
# negative is a confusing refusal with a clear instruction, while the cost of a
# false positive is a build reaching dev with no owner notification.
_INFO_MARKERS = (
    "como ", "como?", "qual ", "quais ", "quanto ", "quanta ", "quando ",
    "onde ", "quem ", "status", "situacao", "andamento", "progresso",
    "existe", "tem ", "tendo", "funciona", "funcionando", "erro",
    "erros", "bug", "incidente", "capacity", "capacidade", "load",
    "latencia", "custo", "preco", "document", "doc", "explic", "ajuda",
    # failure states are information asks, not build asks
    "quebr", "falhou", "falha", "parou", "caiu", "voltou", "voltando",
    "subiu", "subindo", "deu erro", "travou", "travando",
    # inspection requests. "revisa a migration?" asks dev to look at existing
    # work, which is not a build and must not demand a revenue justification.
    "revisa", "revisar", "review", "olha", "confere", "checa", "verifica",
    "da um pulso", "status do",
    "sabe", "podem me passar", "me passar", "confirm", "valid",
)


def _looks_like_information_request(text: str) -> bool:
    folded = " " + _fold(text) + " "
    return any(m in folded for m in _INFO_MARKERS)


def _is_build_capable(team_name: str) -> bool:
    return any(t in _fold(team_name or "") for t in _BUILD_CAPABLE_TEAMS)


def _looks_like_build_request(text: str) -> bool:
    """Whether a cross-team ask is asking for work rather than information.

    A question mark is deliberately NOT a tiebreaker: "voce consegue construir
    um checkout?" is the most natural way to phrase the exact bypass this
    guards, and a trailing "?" would wave it through.
    """
    folded = " " + _fold(text) + " "
    if any(w in folded for w in _PAST_REF):
        return False
    if any(q in folded for q in _QUESTION_FRAMES):
        return False
    return any(stem in folded for stem in _BUILD_STEMS)


def _has_evidence(text: str) -> bool:
    """Whether a justification carries a figure or names a measurable metric."""
    low = (text or "").lower()
    if any(ch.isdigit() for ch in low):
        return True
    return any(h in low for h in _METRIC_HINTS)


class RequestBuildInput(BaseModel):
    requirement: str = Field(
        description="O que quer que o time de DEV construa. Concreto e delimitado."
    )
    revenue_justification: str = Field(
        description=(
            "O FATO que mostra que isso aumenta receita projetada ou melhora o "
            "processo/performance de vendas. Precisa de número: valor, %, "
            "volume, ou a métrica que muda. 'Ajudaria a vender' não passa."
        )
    )
    evidence: str = Field(
        default="",
        description="De onde veio o número: deals, relatório, meta. Opcional mas forte.",
    )
    to_team: str = Field(default="dev", description="Time alvo. Default dev.")
    urgency: str = Field(default="warning", description="info | warning | blocker")


_REQUEST_BUILD_PENDING_ARGS = (
    "requirement", "revenue_justification", "evidence", "to_team", "from_team",
)


async def _verified_approved_request_build(
    marker: Any, org_id: str, tool_args: dict[str, Any]
) -> str | None:
    """Return approved action id only when the marker matches a DB-approved row."""
    if not isinstance(marker, dict):
        return None
    action_id = marker.get("action_id")
    marker_org = marker.get("org_id")
    decided_by = marker.get("decided_by")
    if not all(isinstance(v, str) and v for v in (action_id, marker_org, decided_by)):
        return None
    if marker_org != org_id:
        return None

    from sqlalchemy import select

    from aios.db.engine import async_session
    from aios.db.models import PendingAction

    async with async_session() as sess:
        row = (await sess.execute(select(PendingAction).where(
            PendingAction.id == action_id,
            PendingAction.org_id == org_id,
            PendingAction.status == "approved",
            PendingAction.decided_by == decided_by,
            PendingAction.tool_name == "request_build",
        ))).scalar_one_or_none()
        if row is None:
            return None
        row_args = row.tool_args
        if not isinstance(row_args, dict):
            return None
        if any(row_args.get(k) != tool_args.get(k) for k in _REQUEST_BUILD_PENDING_ARGS):
            return None
        return row.id


class RequestBuildTool(BaseTool):
    name = "request_build"
    description = (
        "Pede ao gerente de OUTRO time que construa algo e OBRIGA o dono a ser "
        "avizado no Slack com o pedido, a análise de viabilidade do gerente "
        "destinatário e a justificativa de receita/performance. Use para pedir "
        "funcionalidade, integração ou correção que melhore vendas. O dono é "
        "sempre contatado — não existe caminho silencioso. Se você não tem um "
        "número que sustente o pedido, não use: colete o dado antes."
    )
    input_model = RequestBuildInput

    async def run(
        self,
        requirement: str,
        revenue_justification: str,
        evidence: str = "",
        to_team: str = "dev",
        urgency: str = "warning",
        *,
        _hitl_approved_action: dict | None = None,
    ) -> dict[str, Any]:
        from aios.db.engine import async_session
        from aios.db.models import Agent, Message

        org_id = _require_org(self._org_id)
        requirement = (requirement or "").strip()
        justification = (revenue_justification or "").strip()

        if not requirement:
            return {"ok": False, "error": "requirement is required"}
        # Fail closed BEFORE contacting anyone. An owner asked to rule on a vague
        # request can only say no, and the requester learns nothing.
        if not _has_evidence(justification):
            return {
                "ok": False,
                "error": (
                    "revenue_justification has no figure or measurable metric. "
                    "Read the real numbers (crm_pipeline_stats, the funnel) and "
                    "state the expected revenue or the process metric it moves. "
                    "The owner is not asked to rule on a wish."
                ),
            }

        depth = _hops.get()
        if depth >= _MAX_HOPS:
            return {
                "ok": False,
                "error": f"collaboration hop limit reached ({_MAX_HOPS}); escalate to a human instead",
            }

        async with async_session() as sess:
            target = await _resolve_team(sess, org_id, to_team)
            if target is None:
                return {"ok": False, "error": f"team not found in this org: {to_team!r}"}
            if not target.manager_agent_id:
                return {"ok": False, "error": f"team {target.name!r} has no manager agent to ask"}
            caller, error = await _caller_team(sess, org_id, "", self._agent_id)
            if caller is None:
                return {"ok": False, "error": error}
            if caller.id == target.id:
                return {"ok": False, "error": f"{target.name!r} is your own team"}

            manager = await sess.get(Agent, target.manager_agent_id)
            if manager is None:
                return {"ok": False, "error": f"manager agent missing for {target.name!r}"}

            conv = await _collab_thread(
                sess, org_id=org_id, to_team=target, from_team=caller, manager=manager
            )
            ask = (
                f"O gerente de {caller.name!r} pediu para o seu time construir:\n\n"
                f"{requirement}\n\n"
                f"Justificativa de negócio apresentada por {caller.name}:\n{justification}"
            )
            if (evidence or "").strip():
                ask += f"\n\nEvidência citada:\n{evidence.strip()}"

            sess.add(Message(
                conversation_id=conv.id,
                org_id=org_id,
                role="user",
                content=ask,
                extra_data={
                    "collab": True,
                    "from_team_id": caller.id,
                    "from_team_name": caller.name,
                    "direction": "build_request",
                },
            ))
            await sess.commit()
            conv_id = conv.id
            target_name = target.name
            manager_name = manager.name
            manager_id = manager.id

        # The dev manager's own answer, requested as a feasibility analysis.
        from aios.core.agent import is_failed_run
        from aios.core.orchestrator import _get_runtime

        feasibility_prompt = (
            "Responda como análise de viabilidade para o dono da empresa, que "
            "vai decidir. Estruture em: (1) o que exatamente sua equipe vai "
            "construir; (2) viabilidade — dá, não dá, dá parcialmente; (3) "
            "esforço estimado; (4) risco; (5) o que NÃO vai resolver. Se a "
            "justificativa de negócio for fraca, diga isso — o dono precisa saber."
        )
        token = _hops.set(depth + 1)
        try:
            feasibility = await _get_runtime(manager, None).run(conv_id, feasibility_prompt)
        except Exception:
            logger.exception("request_build: manager %s failed", manager_id)
            return {
                "ok": False,
                "error": f"manager {manager_name!r} did not answer; request NOT sent to the owner",
                "conversation_id": conv_id,
            }
        finally:
            _hops.reset(token)

        feasibility = (feasibility or "").strip()
        if is_failed_run(feasibility) or not feasibility:
            return {
                "ok": False,
                "error": (
                    f"manager {manager_name!r} produced no feasibility analysis; "
                    "request NOT sent to the owner rather than sent incomplete"
                ),
                "conversation_id": conv_id,
            }

        async with async_session() as sess:
            sess.add(Message(
                conversation_id=conv_id,
                org_id=org_id,
                role="assistant",
                content=feasibility,
                agent_id=manager_id,
                extra_data={"collab": True, "direction": "feasibility"},
            ))
            await sess.commit()

        # The owner always hears about it, with both sides in one message.
        from aios.core.meetings import human_slack_targets
        from aios.core.owner_notify import deliver_owner

        targets = await human_slack_targets(org_id, team_id="")
        if not targets:
            return {
                "ok": False,
                "error": (
                    "no Slack DM wired for the owner; the request was NOT delivered. "
                    "Set one via /dashboard/channels with config.slack_1on1 = true"
                ),
                "conversation_id": conv_id,
                "feasibility": feasibility[:2000],
            }

        icons = {"info": ":information_source:", "warning": ":warning:", "blocker": ":rotating_light:"}
        header = f"{icons.get(urgency, icons['info'])} *BUILD REQUEST* — {caller.name} → {target_name}"
        evidence_line = f"\n\n*Evidência citada:*\n{evidence.strip()}" if (evidence or "").strip() else ""
        text = (
            f"{header}\n\n"
            f"*1. O que {caller.name} pediu que fosse construído:*\n{requirement}\n\n"
            f"*2. Análise de viabilidade — {manager_name} ({target_name}):*\n{feasibility}\n\n"
            f"*3. Justificativa de {caller.name} (receita / performance):*\n{justification}"
            f"{evidence_line}\n\n"
            f"_Aprovação no /dashboard/approvals. Thread: {conv_id}_"
        )
        res = await deliver_owner(
            org_id, text, urgency=urgency or "info", requires_ack=True,
        )
        if not res["ok"]:
            return {
                "ok": False,
                "error": "Slack and Telegram delivery to the owner failed; the request was NOT delivered",
                "conversation_id": conv_id,
                "feasibility": feasibility[:2000],
            }

        # Parked for the owner's decision, so "told" and "decided" are distinct.
        from aios.db.models import PendingAction

        pending_args = {
            "requirement": requirement,
            "revenue_justification": justification,
            "evidence": evidence,
            "to_team": target_name,
            "from_team": caller.name,
        }
        pending_id = await _verified_approved_request_build(
            _hitl_approved_action, org_id, pending_args
        )
        if pending_id is None:
            async with async_session() as sess:
                pa = PendingAction(
                    org_id=org_id,
                    agent_id=self._agent_id or manager_id,
                    conversation_id=conv_id,
                    tool_name="request_build",
                    tool_args=pending_args,
                    context_summary=(
                        f"{caller.name} pediu para {target_name} construir. "
                        f"{manager_name} viability: {feasibility[:400]}"
                    ),
                    status="pending",
                )
                sess.add(pa)
                await sess.commit()
                pending_id = pa.id

        return {
            "ok": True,
            "target_team": target_name,
            "manager": manager_name,
            "feasibility": feasibility[:4000],
            "owner_notified": True,
            "pending_approval_id": pending_id,
            "conversation_id": conv_id,
            "message": "owner notified on Slack; waiting on approval",
        }


TOOL_REGISTRY["request_build"] = {
    "code_reference": "aios.tools.team_collaboration.RequestBuildTool"
}
