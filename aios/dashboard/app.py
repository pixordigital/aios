"""AIOS Dashboard — Jinja2 server-rendered UI.

Auth: All /dashboard/* paths (except login/register/logout) are protected
by middleware in main.py. If adding static files, mount them under
/dashboard/static/ and add the path to AUTH_EXEMPT in main.py.
Currently all CSS/JS is inline or CDN-loaded — no local static files.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from aios.db.backend import db_session
from aios.db.models import Agent, ChannelConnection, Conversation, Invitation, Message, Organization, Team, User, team_agents
from aios.templates import TEMPLATES, apply_template
from aios.api.deps import COOKIE_NAME, create_jwt_token
from aios.api.auth import _validate_password

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=True,
)

# ─── Helpers ───

MODEL_PRICING = {
    "openai/gpt-4o": (2.50, 10.00), "openai/gpt-4o-mini": (0.15, 0.60), "openai/gpt-4.1": (2.50, 10.00),
    "openai/gpt-4.1-mini": (0.40, 1.60), "openai/gpt-4.1-nano": (0.10, 0.40),
    "openai/o3": (5.00, 20.00), "openai/o3-mini": (1.10, 4.40), "openai/o4": (10.00, 40.00),
    "openai/o4-mini": (1.50, 6.00),
    "anthropic/claude-sonnet-4-20250514": (3.00, 15.00), "anthropic/claude-5-opus-20250714": (15.00, 75.00),
    "anthropic/claude-4.5-sonnet": (3.00, 15.00), "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "anthropic/claude-3-haiku": (0.25, 1.25),
    "anthropic/claude-opus-4-20250514": (15.00, 75.00),
    "anthropic/claude-fable-5": (1.50, 7.50),
}

TOOL_DESCRIPTIONS = {
    "calculator": "Expressões matemáticas, avaliação segura",
    "web_search": "Buscar na web",
    "send_email": "Enviar mensagens por e-mail",
    "read_file": "Ler arquivos enviados por ID do artefato",
    "current_datetime": "Obter data/hora UTC atual com fuso",
    "http_get": "Buscar URLs HTTPS",
}


def _cost_estimate(model: str, tokens: int = 4096) -> float:
    if model in MODEL_PRICING:
        inp, out = MODEL_PRICING[model]
        return round((inp * tokens / 1000 + out * tokens / 1000 * 0.5) / 100, 2)
    return 0.0


def _compatible_agent_types(agent_type: str) -> list[str]:
    """Recommend compatible teammates for a given agent type."""
    MAP = {
        "orchestrator": ["manager", "sdr", "closer", "support", "data_analyst", "data_scientist", "custom"],
        "manager": ["orchestrator", "sdr", "closer", "support", "data_analyst", "data_scientist", "custom"],
        "sdr": ["closer", "support", "manager", "custom"],
        "closer": ["sdr", "support", "manager", "custom"],
        "support": ["sdr", "closer", "manager", "custom"],
        "data_analyst": ["data_scientist", "manager", "custom"],
        "data_scientist": ["data_analyst", "manager", "custom"],
        "custom": ["orchestrator", "manager", "sdr", "closer", "support", "data_analyst", "data_scientist"],
    }
    return MAP.get(agent_type, ["custom"])


def _orchestrator_recommendation(agent_ids: list) -> str | None:
    """Suggest which agent should be orchestrator based on team composition."""
    priority = ["orchestrator", "manager", "closer", "sdr", "data_scientist", "custom", "support", "data_analyst"]
    for p in priority:
        for a in agent_ids:
            if a.agent_type == p:
                return a.id
    return None


def _team_compatibility(agents: list) -> dict:
    """Score team compatibility 0-100."""
    if not agents or len(agents) < 2:
        return {"score": 0, "issues": ["Precisa de pelo menos 2 agentes"]}
    types = [a.agent_type for a in agents]
    score = 100
    issues = []
    if len(types) != len(set(types)):
        score -= 20
        issues.append("Tipos de agente duplicados — considere diversificar as funções")
    if any(t == "data_scientist" for t in types) and "data_analyst" not in types:
        score -= 10
        issues.append("Cientista de Dados funciona melhor em par com um Analista de Dados")
    if any(t == "sdr" for t in types) and "closer" not in types:
        score -= 15
        issues.append("Equipe SDR sem Closer para completar o funil de vendas")
    drafted = [a for a in agents if a.status != "active"]
    if drafted:
        score -= 10 * len(drafted)
        issues.append(f"{len(drafted)} {('agente não implantado' if len(drafted) == 1 else 'agentes não implantados')}")
    return {"score": max(score, 0), "issues": issues}


def _tool_conflicts(tools_list: list[list[str]]) -> list[str]:
    """Detect tool conflicts across agents."""
    all_tools = {}
    conflicts = []
    for i, tl in enumerate(tools_list):
        for t in tl:
            if t in all_tools:
                conflicts.append(f"Ferramenta '{t}' usada por vários agentes — pode causar contenção")
            all_tools[t] = i
    return list(set(conflicts))


def _strategy_label(value: str) -> str:
    """Human-readable label for a routing strategy DB value."""
    LABELS = {
        "supervisor": "Supervisor",
        "round_robin": "Rodízio",
        "broadcast": "Broadcast",
        "semantic": "Semântica",
    }
    return LABELS.get(value, value)


def _plan_label(value: str) -> str:
    """Human-readable label for a plan key."""
    from aios.config import PLANS
    return PLANS.get(value, {}).get("name", value)


def _agent_type_label(value: str) -> str:
    """Human-readable label for an agent type DB value."""
    LABELS = {
        "custom": "Personalizado",
        "orchestrator": "Orquestrador",
        "manager": "Gerente",
        "sdr": "SDR",
        "closer": "Closer",
        "support": "Suporte",
        "data_analyst": "Analista de Dados",
        "data_scientist": "Cientista de Dados",
    }
    return LABELS.get(value, value)


def _channel_type_label(value: str) -> str:
    """Human-readable label for a channel type DB value."""
    LABELS = {
        "web": "Web Chat",
        "whatsapp": "WhatsApp",
        "evolution": "Evolution",
        "slack": "Slack",
        "telegram": "Telegram",
        "discord": "Discord",
        "email": "E-mail",
    }
    return LABELS.get(value, value)


def _status_label(value: str) -> str:
    """Human-readable label for an agent status DB value."""
    return "Ativo" if value == "active" else ("Rascunho" if value == "draft" else value)


_env.globals["cost_estimate"] = _cost_estimate
_env.globals["compatible_types"] = _compatible_agent_types
_env.globals["orchestrator_recommendation"] = _orchestrator_recommendation
_env.globals["team_compatibility"] = _team_compatibility
_env.globals["tool_conflicts"] = _tool_conflicts
_env.globals["tool_descriptions"] = TOOL_DESCRIPTIONS
_env.globals["strategy_label"] = _strategy_label
_env.globals["plan_label"] = _plan_label
_env.globals["agent_type_label"] = _agent_type_label
_env.globals["channel_type_label"] = _channel_type_label
_env.globals["status_label"] = _status_label


async def _render(name: str, request: Request, **kw) -> str:
    t = _env.get_template(name)
    state = getattr(request, "state", None)
    orgs = None
    active_org_id = None
    is_sa = getattr(state, "is_superadmin", False) if state else False
    if is_sa:
        async with db_session() as db:
            orgs = (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
    active_org_id = getattr(state, "org_id", None) if state else None
    if "agent_templates" not in kw:
        kw["agent_templates"] = TEMPLATES
    return t.render({
        "request": request,
        "user_email": getattr(state, "user_email", None) if state else None,
        "is_superadmin": is_sa,
        "is_impersonating": getattr(state, "is_impersonating", False) if state else False,
        "orgs": orgs,
        "active_org_id": active_org_id,
        **kw,
    })


# ─── Auth routes ───

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return await _render("login.html", request, title="Entrar", error=error)


@router.post("/login", response_class=HTMLResponse)
async def login_action(request: Request, email: str = Form(...), password: str = Form(...)):
    from aios.api.auth import _verify_password, _rate_limit
    from sqlalchemy import select
    client_ip = request.client.host if request.client else "unknown"
    try:
        await _rate_limit(f"{email.lower().strip()}:{client_ip}")
    except HTTPException:
        return await login_page(request, error="Muitas tentativas de login. Tente novamente mais tarde.")
    async with db_session() as db:
        result = await db.execute(select(User).where(User.email == email.lower().strip()))
        user = result.scalar_one_or_none()
        if not user or not _verify_password(password, user.hashed_password):
            return await login_page(request, error="E-mail ou senha inválidos")

        token = create_jwt_token(user.id, user.org_id)
        resp = RedirectResponse("/dashboard", status_code=303)
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp.set_cookie(
            key=COOKIE_NAME, value=token,
            max_age=86400 * 7, httponly=True, secure=is_https, samesite="strict",
            path="/",
        )
        return resp


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str = ""):
    return await _render("register.html", request, title="Registrar", error=error)


@router.post("/register", response_class=HTMLResponse)
async def register_action(
    request: Request,
    name: str = Form(...), email: str = Form(...),
    password: str = Form(...), org_name: str = Form(...),
):
    try:
        _validate_password(password)
    except Exception as e:
        return await register_page(request, error=str(e.detail) if hasattr(e, "detail") else str(e))

    from aios.api.auth import _hash_password
    async with db_session() as db:
        from sqlalchemy import select
        existing = await db.execute(select(User).where(User.email == email.lower().strip()))
        if existing.scalar_one_or_none():
            return await register_page(request, error="E-mail já registrado")

        # first-ever user gets superadmin — count BEFORE creating the org so two
        # concurrent registrations can't both read 0 and both become superadmin
        user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
        role = "superadmin" if user_count == 0 else "org_admin"

        slug = org_name.lower().strip().replace(" ", "-")
        slug = "".join(c for c in slug if c.isalnum() or c in "-_") or "org"
        if slug in ("pixor", "default", "admin", "api", "dashboard"):
            return await register_page(request, error="Nome da organização reservado. Escolha outro nome.")
        existing_org = await db.execute(select(Organization).where(Organization.slug == slug))
        if existing_org.scalar_one_or_none():
            return await register_page(request, error="Nome da organização já existe. Escolha outro nome.")
        org = Organization(name=org_name, slug=slug)
        db.add(org)
        try:
            await db.flush()
        except Exception as e:
            from sqlalchemy.exc import IntegrityError
            if isinstance(e, IntegrityError) or "UniqueViolation" in type(e).__name__ or "duplicate key" in str(e).lower():
                await db.rollback()
                return await register_page(request, error="Nome da organização já existe. Escolha outro nome.")
            raise
        user = User(
            email=email.lower().strip(),
            hashed_password=_hash_password(password),
            org_id=org.id,
            role=role,
        )
        db.add(user)
        try:
            await db.commit()
        except Exception as e:
            from sqlalchemy.exc import IntegrityError
            if isinstance(e, IntegrityError) or "duplicate key" in str(e).lower():
                await db.rollback()
                return await register_page(request, error="E-mail já registrado")
            raise

        token = create_jwt_token(user.id, user.org_id)
        resp = RedirectResponse("/dashboard", status_code=303)
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp.set_cookie(
            key=COOKIE_NAME, value=token,
            max_age=86400 * 7, httponly=True, secure=is_https, samesite="strict",
            path="/",
        )
        return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/dashboard/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp




async def _resolve_org_id(request: Request) -> str:
    """Get org_id from request state (set by cookie auth middleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id:
        return org_id
    fallback = await _default_org_id()
    return fallback


async def _default_org_id() -> str:
    async with db_session() as db:
        org = (await db.execute(select(Organization).where(Organization.slug == "pixor"))).scalar_one_or_none()
        if org:
            return org.id
        org = (await db.execute(select(Organization).where(Organization.slug == "default"))).scalar_one_or_none()
        return org.id if org else "none"


async def _org_filter(request: Request) -> str:
    """Get org_id for data filtering — from cookie if available, fallback to default."""
    org_id = getattr(request.state, "org_id", None) or await _default_org_id()
    return org_id


# ─── Dashboard ───

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        ac = (await db.execute(select(func.count(Agent.id)).where(Agent.org_id == org_id))).scalar() or 0
        tc = (await db.execute(select(func.count(Team.id)).where(Team.org_id == org_id))).scalar() or 0
        cc = (await db.execute(select(func.count(Conversation.id)).where(Conversation.org_id == org_id))).scalar() or 0
        mc = (await db.execute(select(func.count(Message.id)))).scalar() or 0
        teams = (await db.execute(
            select(Team).options(selectinload(Team.agents)).where(Team.org_id == org_id).order_by(Team.created_at.desc())
        )).scalars().all()
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
        total_cost = sum(_cost_estimate(a.llm_config.get("model", ""), a.llm_config.get("max_tokens", 4096)) for a in agents if a.llm_config)
        from aios.core.limits import get_monthly_usage
        usage_monthly = await get_monthly_usage(org_id, db)
    return await _render("dashboard.html", request, title="Dashboard",
                   stats={"agents": ac, "teams": tc, "conversations": cc, "messages": mc,
                          "total_cost": total_cost, "deployed": sum(1 for a in agents if a.status == "active")},
                   teams=teams, agents=agents, usage_monthly=usage_monthly)


# ─── Analytics Dashboard ───

@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Analytics & Telemetry dashboard."""
    return await _render("analytics.html", request, title="Análises")


# ─── Agent CRUD ───

AGENT_TYPES = ["custom", "orchestrator", "manager", "sdr", "closer", "support", "data_analyst", "data_scientist"]
ROUTING_STRATEGIES = ["supervisor", "round_robin", "broadcast", "semantic"]


@router.get("/agents", response_class=HTMLResponse)
async def agent_list(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.created_at.desc()))).scalars().all()
        teams_map = {}
        result = await db.execute(
            select(Team).options(selectinload(Team.agents)).where(Team.org_id == org_id)
        )
        for t in result.scalars():
            for a in (t.agents or []):
                teams_map.setdefault(a.id, []).append(t.name)
    return await _render("agents.html", request, title="Agentes", agents=agents, teams_map=teams_map)


@router.get("/agents/new", response_class=HTMLResponse)
async def agent_new_form(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
    return await _render("agent_form.html", request, title="Novo Agente",
                   agent=None, agent_types=AGENT_TYPES, agents=agents)


@router.get("/agents/{aid}/edit", response_class=HTMLResponse)
async def agent_edit_form(request: Request, aid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agent = await db.get(Agent, aid)
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
        if not agent:
            return RedirectResponse("/dashboard/agents", status_code=303)
    return await _render("agent_form.html", request, title="Editar Agente",
                   agent=agent, agent_types=AGENT_TYPES, agents=agents)


@router.get("/agents/{aid}/clone")
async def agent_clone(request: Request, aid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        src = await db.get(Agent, aid)
        if not src or src.org_id != org_id:
            return RedirectResponse("/dashboard/agents", status_code=303)
        agent = Agent(
            org_id=src.org_id, name=f"{src.name} (copy)",
            agent_type=src.agent_type, system_prompt=src.system_prompt,
            llm_config=dict(src.llm_config) if src.llm_config else {},
            tools=list(src.tools) if src.tools else [],
            memory_config=dict(src.memory_config) if src.memory_config else {},
        )
        db.add(agent)
        await db.flush()
        from aios.db.models import AgentVersion as _AV2
        from sqlalchemy import func as _f2, select as _s2
        db.add(_AV2(agent_id=agent.id, org_id=agent.org_id, version=1, name=agent.name, system_prompt=agent.system_prompt, llm_config=dict(agent.llm_config or {}), tools=list(agent.tools or []), memory_config=dict(agent.memory_config or {}), governance_config=dict(agent.governance_config or {}), agent_type=agent.agent_type, change_note="clone"))
        await db.commit()
    return RedirectResponse("/dashboard/agents", status_code=303)


@router.post("/agents/save")
async def agent_save(
    request: Request,
    agent_id: str = Form(""),
    name: str = Form(...),
    agent_type: str = Form("custom"),
    system_prompt: str = Form(""),
    model: str = Form("openai/gpt-4o"),
    temperature: float = Form(0.7),
    max_tokens: int = Form(4096),
    tools: str = Form(""),
    short_term_buffer: int = Form(50),
    long_term_enabled: bool = Form(False),
    episodic_enabled: bool = Form(False),
):
    if agent_type not in AGENT_TYPES:
        return HTMLResponse(f"<h2>Tipo inválido: {agent_type}</h2><a href='/dashboard/agents'>Voltar</a>", status_code=422)
    if not (0 <= temperature <= 2):
        return HTMLResponse("<h2>temperature 0..2</h2>", status_code=422)
    if not (256 <= max_tokens <= 16384):
        return HTMLResponse("<h2>max_tokens 256..16384</h2>", status_code=422)
    org_id = await _resolve_org_id(request)
    async with db_session() as db:
        tools_list = [t.strip() for t in tools.replace(",", " ").split() if t.strip()]
        if tools_list:
            try:
                from aios.tools.registry import TOOL_REGISTRY as _REG
                _allowed = set(_REG.keys()) or {"calculator","web_search","send_email","read_file","current_datetime","http_get","http_request","code","transform","if_branch","wait","hubspot","pipedrive","rdstation","transcribe","lead_score","sql_query","python_sandbox"}
            except Exception:
                _allowed = {"calculator","web_search","send_email","read_file","current_datetime","http_get","http_request","code","transform","if_branch","wait","hubspot","pipedrive","rdstation","transcribe","lead_score","sql_query","python_sandbox"}
            _bad = [t for t in tools_list if t not in _allowed]
            if _bad:
                return HTMLResponse(f"<h2>tools inválidas: {_bad}</h2>", status_code=422)
        llm_config = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
        memory_config = {
            "short_term": {"max_messages": short_term_buffer},
            "long_term": {"enabled": long_term_enabled, "top_k": 5},
            "episodic": {"enabled": episodic_enabled, "summarize_after": 10},
        }
        if agent_id:
            agent = await db.get(Agent, agent_id)
            if agent and agent.org_id == org_id:
                from sqlalchemy import select as _select, func as _func
                from aios.db.models import AgentVersion
                max_v = (await db.execute(_select(_func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent.id))).scalar() or 0
                db.add(AgentVersion(agent_id=agent.id, org_id=agent.org_id, version=max_v+1, name=agent.name, system_prompt=agent.system_prompt, llm_config=dict(agent.llm_config or {}), tools=list(agent.tools or []), memory_config=dict(agent.memory_config or {}), governance_config=dict(agent.governance_config or {}), agent_type=agent.agent_type, change_note="pre-edit snapshot"))
                agent.name = name; agent.agent_type = agent_type
                agent.system_prompt = system_prompt; agent.llm_config = llm_config
                agent.tools = tools_list; agent.memory_config = memory_config
                await db.flush()
                # pós-edit snapshot (P0-3)
                db.add(AgentVersion(agent_id=agent.id, org_id=agent.org_id, version=max_v+2, name=agent.name, system_prompt=agent.system_prompt, llm_config=dict(agent.llm_config or {}), tools=list(agent.tools or []), memory_config=dict(agent.memory_config or {}), governance_config=dict(agent.governance_config or {}), agent_type=agent.agent_type, change_note="post-edit"))
        else:
            # per-field template fallback (desacoplado de system_prompt)
            tpl = apply_template(agent_type) if agent_type != "custom" else None
            final_prompt = system_prompt.strip() if system_prompt.strip() else (tpl.get("system_prompt", "") if tpl else "")
            # llm: if form left at defaults, use template
            _is_default_llm = (model == "openai/gpt-4o" and temperature == 0.7 and max_tokens == 4096)
            final_llm = llm_config if not tpl or not _is_default_llm else tpl.get("llm_config", llm_config)
            final_tools = tools_list if tools_list else (tpl.get("tools", []) if tpl else [])
            _is_default_mem = (short_term_buffer == 50 and not long_term_enabled and not episodic_enabled)
            final_mem = memory_config if not tpl or not _is_default_mem else tpl.get("memory_config", memory_config)
            agent = Agent(
                org_id=org_id,
                name=name, agent_type=agent_type,
                system_prompt=final_prompt,
                llm_config=final_llm,
                tools=final_tools,
                memory_config=final_mem,
            )
            db.add(agent)
            await db.flush()
            from sqlalchemy import select as _select2, func as _func2
            from aios.db.models import AgentVersion
            db.add(AgentVersion(agent_id=agent.id, org_id=agent.org_id, version=1, name=agent.name, system_prompt=agent.system_prompt, llm_config=dict(agent.llm_config or {}), tools=list(agent.tools or []), memory_config=dict(agent.memory_config or {}), governance_config=dict(agent.governance_config or {}), agent_type=agent.agent_type, change_note="initial"))
        await db.commit()
    return RedirectResponse("/dashboard/agents", status_code=303)


@router.get("/agents/{aid}/deploy")
async def agent_deploy(request: Request, aid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agent = await db.get(Agent, aid)
        if agent and agent.org_id == org_id:
            if agent.status != "active":
                from aios.config import PLANS
                from aios.db.models import Organization as _Org
                _org = await db.get(_Org, org_id)
                _plan = ((_org.extra_data or {}).get("plan", "free") if _org else "free")
                if _plan not in ("unlimited",):
                    _limits = PLANS.get(_plan, PLANS["free"])
                    _cnt = (await db.execute(select(Agent).where(Agent.org_id == org_id, Agent.status == "active"))).scalars().all()
                    if len(_cnt) >= _limits.get("max_agents", 2):
                        return HTMLResponse(f"<h2>quota max_agents {_limits['max_agents']} para {_plan}</h2>", status_code=403)
            agent.status = "active" if agent.status != "active" else "draft"
            await db.commit()
    return RedirectResponse("/dashboard/agents", status_code=303)


@router.post("/agents/{aid}/test")
async def agent_test(request: Request, aid: str, message: str = Form("Olá, teste rápido")):
    """Dry-run 1 caso antes de ativar — reusa sandbox proxy."""
    from fastapi.responses import JSONResponse
    org_id = await _org_filter(request)
    async with db_session() as db:
        agent = await db.get(Agent, aid)
        if not agent or agent.org_id != org_id:
            return JSONResponse({"error": "not found"}, status_code=404)
        from aios.core.agent import AgentRuntime
        import uuid
        cid = f"test_{uuid.uuid4().hex[:8]}"
        runtime = AgentRuntime(agent, None)
        try:
            out = await runtime.run(cid, message, db)
            return JSONResponse({"ok": True, "output": out[:2000]})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)[:500]}, status_code=200)


@router.get("/api/models")
async def api_models():
    """Fonte única de modelos — reusa MODEL_PRICING."""
    from fastapi.responses import JSONResponse
    models = []
    for m, (inp, out) in MODEL_PRICING.items():
        models.append({"model": m, "input": inp, "output": out, "cost_estimate": _cost_estimate(m)})
    # add ollama/opencode extras not in pricing
    for m in ["ollama/llama3","ollama/mistral","opencode/deepseek-v4"]:
        if m not in MODEL_PRICING:
            models.append({"model": m, "input": 0, "output": 0, "cost_estimate": 0})
    return JSONResponse(models)


@router.get("/agents/wizard", response_class=HTMLResponse)
async def agent_wizard(request: Request):
    return await _render("wizard.html", request, title="Assistente — Novo Agente", agent_types=AGENT_TYPES)


@router.get("/agents/{aid}/delete")
async def agent_delete(request: Request, aid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agent = await db.get(Agent, aid)
        if agent and agent.org_id == org_id:
            await db.delete(agent)
            await db.commit()
    return RedirectResponse("/dashboard/agents", status_code=303)


# ─── Team CRUD ───

@router.get("/teams", response_class=HTMLResponse)
async def team_list(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        teams = (await db.execute(
            select(Team).options(selectinload(Team.agents)).where(Team.org_id == org_id).order_by(Team.created_at.desc())
        )).scalars().all()
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
        compat_scores = {t.id: _team_compatibility(t.agents or []) for t in teams}
    return await _render("teams.html", request, title="Equipes", teams=teams, agents=agents, compat_scores=compat_scores)


@router.get("/teams/new", response_class=HTMLResponse)
async def team_new_form(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
    return await _render("team_form.html", request, title="Nova Equipe",
                   team=None, agents=agents, strategies=ROUTING_STRATEGIES)


@router.get("/teams/{tid}/edit", response_class=HTMLResponse)
async def team_edit_form(request: Request, tid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        team = await db.get(
            Team, tid,
            options=(selectinload(Team.agents),)
        )
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
        if not team:
            return RedirectResponse("/dashboard/teams", status_code=303)
    return await _render("team_form.html", request, title="Editar Equipe",
                   team=team, agents=agents, strategies=ROUTING_STRATEGIES)


@router.get("/teams/{tid}/recommend-orchestrator")
async def recommend_orchestrator(tid: str):
    async with db_session() as db:
        team = await db.get(Team, tid)
        if team and team.agents:
            rec = _orchestrator_recommendation(team.agents)
            agents_list = [a for a in team.agents]
            return HTMLResponse(f"""
            <div style="font-size:0.8125rem;color:var(--accent);padding:0.5rem 0">
                Recomendação: <strong>{next((a.name for a in agents_list if a.id == rec), '—')}</strong>
                (com base na hierarquia de funções)
            </div>""")
    return HTMLResponse("<div style='font-size:0.8125rem;color:var(--text-tertiary);padding:0.5rem 0'>Selecione os agentes primeiro</div>")


@router.post("/teams/save")
async def team_save(
    request: Request,
    team_id: str = Form(""),
    name: str = Form(...),
    routing_strategy: str = Form("supervisor"),
    orchestrator_agent_id: str = Form(""),
    manager_agent_id: str = Form(""),
    agent_ids: list[str] = Form(default=[]),
):
    org_id = await _resolve_org_id(request)
    async with db_session() as db:
        agent_count = (await db.execute(select(func.count(Agent.id)).where(Agent.org_id == org_id))).scalar() or 0
        if agent_count > 0 and not orchestrator_agent_id:
            return RedirectResponse("/dashboard/teams/new?error=orchestrator-required", status_code=303)
        # validate orchestrator/manager belong to org and in list
        if orchestrator_agent_id:
            _o = await db.get(Agent, orchestrator_agent_id)
            if not _o or _o.org_id != org_id:
                return HTMLResponse("<h2>Orquestrador inválido</h2>", status_code=422)
        if manager_agent_id:
            _m = await db.get(Agent, manager_agent_id)
            if not _m or _m.org_id != org_id:
                return HTMLResponse("<h2>Manager inválido</h2>", status_code=422)

        all_ids = list(agent_ids)
        if orchestrator_agent_id and orchestrator_agent_id not in all_ids:
            all_ids.append(orchestrator_agent_id)
        if manager_agent_id and manager_agent_id not in all_ids:
            all_ids.append(manager_agent_id)
        # tool conflict check
        if all_ids:
            _agents = (await db.execute(select(Agent).where(Agent.id.in_(all_ids), Agent.org_id == org_id))).scalars().all()
            if len(_agents) != len(set(all_ids)):
                return HTMLResponse("<h2>Agente inválido ou de outra org</h2>", status_code=422)
            _conf = _tool_conflicts([a.tools or [] for a in _agents])
            if _conf:
                return HTMLResponse(f"<h2>Conflito de tools: {'; '.join(_conf)}</h2>", status_code=422)

        if team_id:
            team = await db.get(Team, team_id)
            if team and team.org_id == org_id:
                team.name = name; team.routing_strategy = routing_strategy
                team.orchestrator_agent_id = orchestrator_agent_id or None
                team.manager_agent_id = manager_agent_id or None
                # clear + re-assign agents via table to avoid lazy load
                await db.execute(team_agents.delete().where(team_agents.c.team_id == team.id))
                for priority, aid in enumerate(all_ids):
                    await db.execute(team_agents.insert().values(team_id=team.id, agent_id=aid, priority=priority))
        else:
            team = Team(
                org_id=org_id,
                name=name, routing_strategy=routing_strategy,
                orchestrator_agent_id=orchestrator_agent_id or None,
                manager_agent_id=manager_agent_id or None,
            )
            db.add(team); await db.flush()
            for priority, aid in enumerate(all_ids):
                await db.execute(team_agents.insert().values(team_id=team.id, agent_id=aid, priority=priority))
        await db.commit()
    return RedirectResponse("/dashboard/teams", status_code=303)


@router.get("/teams/{tid}/delete")
async def team_delete(request: Request, tid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        team = await db.get(Team, tid)
        if team and team.org_id == org_id:
            await db.delete(team); await db.commit()
    return RedirectResponse("/dashboard/teams", status_code=303)


# ─── Conversations, Channels (unchanged) ───

@router.get("/conversations", response_class=HTMLResponse)
async def conversation_list(request: Request, q: str = "", page: int = 1):
    org_id = await _org_filter(request)
    per = 20
    async with db_session() as db:
        base = select(Conversation).where(Conversation.org_id == org_id)
        if q:
            base = base.where((Conversation.channel.ilike(f"%{q}%")) | (Conversation.external_id.ilike(f"%{q}%")))
        total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
        convs = (await db.execute(base.order_by(Conversation.created_at.desc()).limit(per).offset((page-1)*per))).scalars().all()
        for conv in convs:
            cnt = (await db.execute(select(func.count(Message.id)).where(Message.conversation_id == conv.id))).scalar() or 0
            conv._msg_count = cnt
    return await _render("conversations.html", request, title="Conversas", conversations=convs, q=q, page=page, total=total, per=per)


@router.post("/conversations/{conv_id}/handover")
async def conversation_handover(request: Request, conv_id: str, action: str = Form("take")):
    org_id = await _org_filter(request)
    async with db_session() as db:
        conv = await db.get(Conversation, conv_id)
        if not conv or conv.org_id != org_id:
            return RedirectResponse("/dashboard/conversations", status_code=303)
        extra = dict(conv.extra_data or {})
        h = dict(extra.get("handover", {}))
        if action == "take":
            h.update({"status": "human", "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
        else:
            h.update({"status": "bot", "at": None})
        extra["handover"] = h
        conv.extra_data = extra
        await db.commit()
    return RedirectResponse(f"/dashboard/conversations/{conv_id}", status_code=303)


@router.post("/conversations/{conv_id}/human")
async def conversation_human_reply(request: Request, conv_id: str, content: str = Form(...)):
    org_id = await _org_filter(request)
    async with db_session() as db:
        conv = await db.get(Conversation, conv_id)
        if not conv or conv.org_id != org_id:
            return RedirectResponse("/dashboard/conversations", status_code=303)
        msg = Message(conversation_id=conv_id, role="assistant", content=content, org_id=org_id, extra_data={"human": True})
        db.add(msg)
        await db.commit()
        # deliver via channel
        try:
            from aios.channels.manager import manager as _mgr

            ch_conn = await db.get(__import__("aios.db.models", fromlist=["ChannelConnection"]).ChannelConnection, conv.channel_connection_id) if conv.channel_connection_id else None
            if ch_conn:
                ch = _mgr.build(ch_conn)
                from aios.channels.base import OutboundMessage

                await ch.send(OutboundMessage(text=content, conversation_id=conv_id, extra_data={"from_number": (conv.extra_data or {}).get("from_number", "")}))
        except Exception:
            pass
    return RedirectResponse(f"/dashboard/conversations/{conv_id}", status_code=303)


@router.get("/conversations/{conv_id}/handover-status")
async def conversation_handover_status(request: Request, conv_id: str):
    org_id = await _org_filter(request)
    from fastapi.responses import JSONResponse

    async with db_session() as db:
        conv = await db.get(Conversation, conv_id)
        if not conv or conv.org_id != org_id:
            return JSONResponse({"handover": {"status": "bot"}, "pending": []}, status_code=404)
        h = (conv.extra_data or {}).get("handover", {"status": "bot"})
        pending = []
        try:
            from aios.db.models import PendingAction

            pending_q = (await db.execute(select(PendingAction).where(PendingAction.conversation_id == conv_id, PendingAction.status == "pending"))).scalars().all()
            pending = [{"id": p.id, "tool_name": p.tool_name, "tool_args": p.tool_args, "context_summary": p.context_summary} for p in pending_q]
        except Exception:
            pass
        return JSONResponse({"handover": h, "pending": pending})


@router.get("/conversations/{conv_id}/delete")
async def conversation_delete(request: Request, conv_id: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        conv = await db.get(Conversation, conv_id)
        if conv and conv.org_id == org_id:
            # delete associated messages first
            await db.execute(Message.__table__.delete().where(Message.conversation_id == conv.id))
            await db.delete(conv)
            await db.commit()
    return RedirectResponse("/dashboard/conversations", status_code=303)


@router.get("/conversations/{conv_id}", response_class=HTMLResponse)
async def conversation_detail(request: Request, conv_id: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        conv = await db.get(Conversation, conv_id)
        if not conv or conv.org_id != org_id:
            return HTMLResponse("<h2>Não encontrado</h2><a href='/dashboard/conversations'>Voltar</a>", status_code=404)
        msgs = (await db.execute(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc())
        )).scalars().all()
    return await _render("conversation_detail.html", request, title="Conversa",
                   conv=conv, messages=msgs)


@router.get("/channels", response_class=HTMLResponse)
async def channel_list(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        channels = (await db.execute(select(ChannelConnection).where(ChannelConnection.org_id == org_id).order_by(ChannelConnection.created_at.desc()))).scalars().all()
    return await _render("channels.html", request, title="Canais", channels=channels)


@router.get("/channels/new", response_class=HTMLResponse)
async def channel_new_form(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
        teams = (await db.execute(select(Team).where(Team.org_id == org_id).order_by(Team.name))).scalars().all()
    return await _render("channel_form.html", request, title="Novo Canal", channel=None, agents=agents, teams=teams)


@router.get("/channels/{cid}/edit", response_class=HTMLResponse)
async def channel_edit_form(request: Request, cid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        channel = await db.get(ChannelConnection, cid)
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
        teams = (await db.execute(select(Team).where(Team.org_id == org_id).order_by(Team.name))).scalars().all()
        if not channel:
            return RedirectResponse("/dashboard/channels", status_code=303)
    return await _render("channel_form.html", request, title="Editar Canal", channel=channel, agents=agents, teams=teams)


CHANNEL_CONFIG_FIELDS = {
    "whatsapp": ["config_whatsapp_token", "config_whatsapp_phone"],
    "evolution": ["config_evo_server", "config_evo_key", "config_evo_instance"],
    "slack": ["config_slack_token", "config_slack_secret"],
    "telegram": ["config_telegram_token"],
    "discord": ["config_discord_token"],
    "email": ["config_email_imap", "config_email_smtp", "config_email_addr", "config_email_pass"],
}


@router.post("/channels/save")
async def channel_save(
    request: Request,
    channel_id: str = Form(""), label: str = Form(...), channel_type: str = Form(...),
    agent_id: str = Form(""), team_id: str = Form(""),
    config_whatsapp_token: str = Form(""), config_whatsapp_phone: str = Form(""),
    config_whatsapp_provider: str = Form("meta"),
    config_whatsapp_template: str = Form(""), config_whatsapp_lang: str = Form("pt_BR"),
    config_zernio_key: str = Form(""), config_zernio_account: str = Form(""),
    config_zernio_template: str = Form(""), config_zernio_lang: str = Form("en_US"),
    config_evo_server: str = Form(""), config_evo_key: str = Form(""), config_evo_instance: str = Form(""),
    config_slack_token: str = Form(""), config_slack_secret: str = Form(""),
    config_telegram_token: str = Form(""), config_discord_token: str = Form(""),
    config_email_imap: str = Form(""), config_email_smtp: str = Form(""),
    config_email_addr: str = Form(""), config_email_pass: str = Form(""),
):
    config = {"web": {"platform": "WebSocket"}}.get(channel_type, {})
    if channel_type == "whatsapp":
        if config_whatsapp_provider == "zernio":
            config = {
                "provider": "zernio",
                "api_key": config_zernio_key,
                "account_id": config_zernio_account,
                "template_name": config_zernio_template,
                "template_language": config_zernio_lang,
            }
        else:
            config = {"access_token": config_whatsapp_token, "phone_id": config_whatsapp_phone}
            if config_whatsapp_template:
                config["template_name"] = config_whatsapp_template
                config["template_language"] = config_whatsapp_lang or "pt_BR"
    elif channel_type == "slack":
        config = {"bot_token": config_slack_token, "signing_secret": config_slack_secret}
    elif channel_type == "telegram":
        config = {"bot_token": config_telegram_token}
    elif channel_type == "discord":
        config = {"bot_token": config_discord_token}
    elif channel_type == "evolution":
        config = {"server_url": config_evo_server, "api_key": config_evo_key, "instance": config_evo_instance}
    elif channel_type == "email":
        config = {"imap_server": config_email_imap, "smtp_server": config_email_smtp, "email": config_email_addr, "password": config_email_pass}

    from aios.core.secrets import encrypt_channel_config
    config = encrypt_channel_config(config)
    async with db_session() as db:
        if channel_id:
            ch = await db.get(ChannelConnection, channel_id)
            if ch and ch.org_id == await _resolve_org_id(request):
                ch.label = label; ch.channel_type = channel_type; ch.config = config
                ch.agent_id = agent_id or None; ch.team_id = team_id or None
        else:
            ch = ChannelConnection(
                org_id=await _resolve_org_id(request),
                label=label, channel_type=channel_type, config=config,
                agent_id=agent_id or None, team_id=team_id or None,
            )
            db.add(ch)
        await db.commit()
    return RedirectResponse("/dashboard/channels", status_code=303)


@router.get("/channels/{cid}/toggle")
async def channel_toggle(request: Request, cid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        ch = await db.get(ChannelConnection, cid)
        if ch and ch.org_id == org_id:
            ch.is_active = not ch.is_active; await db.commit()
    return RedirectResponse("/dashboard/channels", status_code=303)


@router.get("/channels/{cid}/delete")
async def channel_delete(request: Request, cid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        ch = await db.get(ChannelConnection, cid)
        if ch and ch.org_id == org_id:
            await db.delete(ch)
            await db.commit()
    return RedirectResponse("/dashboard/channels", status_code=303)


@router.get("/channels/whatsapp/warmup", response_class=HTMLResponse)
async def whatsapp_warmup(request: Request):
    org_id = await _org_filter(request)
    return await _render("whatsapp_warmup.html", request, title="WhatsApp Warmup Checklist")


# ─── Members & Invites ───

@router.get("/members", response_class=HTMLResponse)
async def member_list(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        users = (await db.execute(select(User).where(User.org_id == org_id).order_by(User.created_at))).scalars().all()
        invites = (await db.execute(
            select(Invitation).where(Invitation.org_id == org_id, Invitation.accepted == False).order_by(Invitation.created_at.desc())
        )).scalars().all()
    current_email = getattr(request.state, "user_email", "")
    return await _render("members.html", request, title="Membros", users=users, invites=invites, current_user_email=current_email)


@router.post("/members/invite")
async def member_invite(request: Request, email: str = Form(...), role: str = Form("member")):
    org_id = await _org_filter(request)
    async with db_session() as db:
        existing = (await db.execute(select(User).where(User.email == email, User.org_id == org_id))).scalar_one_or_none()
        if existing:
            return RedirectResponse("/dashboard/members?error=already-member", status_code=303)
        inv = Invitation(
            org_id=org_id, email=email.lower().strip(), role=role,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(inv)
        await db.commit()
    return RedirectResponse("/dashboard/members", status_code=303)


@router.get("/members/invite/{inv_id}/revoke")
async def member_invite_revoke(request: Request, inv_id: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        inv = await db.get(Invitation, inv_id)
        if inv and inv.org_id == org_id:
            await db.delete(inv)
            await db.commit()
    return RedirectResponse("/dashboard/members", status_code=303)


@router.get("/members/{uid}/remove")
async def member_remove(request: Request, uid: str):
    org_id = await _org_filter(request)
    async with db_session() as db:
        user = await db.get(User, uid)
        if user and user.org_id == org_id and user.role != "superadmin":
            await db.delete(user)
            await db.commit()
    return RedirectResponse("/dashboard/members", status_code=303)


@router.get("/invite/accept")
async def accept_invite(request: Request, token: str = ""):
    """Accept invite link from email."""
    async with db_session() as db:
        inv = (await db.execute(
            select(Invitation).where(Invitation.token == token, Invitation.accepted == False)
        )).scalar_one_or_none()
        if not inv:
            return HTMLResponse("<h2>Convite inválido ou expirado</h2><p>Este link de convite não é mais válido.</p>")

        if getattr(request.state, "user_email", None):
            # logged in — add to org, but only for the invite's own email and
            # never promote to superadmin (prevents account takeover via link).
            from aios.api.deps import get_dashboard_user
            user = await get_dashboard_user(request)
            if user:
                if user.email.lower() != inv.email.lower():
                    return HTMLResponse("<h2>Este convite é para outro e-mail</h2><p>Sai da conta e aceite-o com o endereço convidado.</p>")
                if inv.role == "superadmin":
                    return HTMLResponse("<h2>Convite inválido</h2><p>Convites não podem conceder superadmin.</p>")
                user.org_id = inv.org_id
                user.role = inv.role
                inv.accepted = True
                await db.commit()
                return RedirectResponse("/dashboard", status_code=303)

        # not logged in — redirect to register with invite details
        return RedirectResponse(f"/dashboard/register?invite={inv.token}", status_code=303)


# ─── Admin Panel (superadmin only) ───

async def _require_superadmin(request: Request):
    """Check current user is superadmin, raise 403 if not."""
    from aios.api.deps import get_dashboard_user
    user = await get_dashboard_user(request)
    if not user or user.role != "superadmin":
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<h2>Acesso negado</h2><p>Privilégios de superadmin necessários.</p><a href='/dashboard'>Voltar</a>", status_code=403)
    return user


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    async with db_session() as db:
        org_rows = (await db.execute(select(Organization).order_by(Organization.created_at.desc()))).scalars().all()
        from aios.core.limits import get_usage_summary
        orgs_data = []
        for org in org_rows:
            uc = (await db.execute(select(func.count(User.id)).where(User.org_id == org.id))).scalar() or 0
            ac = (await db.execute(select(func.count(Agent.id)).where(Agent.org_id == org.id))).scalar() or 0
            tc = (await db.execute(select(func.count(Team.id)).where(Team.org_id == org.id))).scalar() or 0
            usage = await get_usage_summary(org.id, db)
            orgs_data.append({"org": org, "user_count": uc, "agent_count": ac, "team_count": tc, "usage": usage})
    return await _render("admin/orgs.html", request, title="Administração", orgs=orgs_data)


@router.get("/admin/orgs/{oid}", response_class=HTMLResponse)
async def admin_org_detail(request: Request, oid: str):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    async with db_session() as db:
        org = await db.get(Organization, oid)
        if not org:
            return HTMLResponse("<h2>Não encontrado</h2>", status_code=404)
        users = (await db.execute(select(User).where(User.org_id == oid).order_by(User.created_at))).scalars().all()
        agents = (await db.execute(select(Agent).where(Agent.org_id == oid).order_by(Agent.name))).scalars().all()
        teams = (await db.execute(select(Team).where(Team.org_id == oid).order_by(Team.name))).scalars().all()
        channels = (await db.execute(select(ChannelConnection).where(ChannelConnection.org_id == oid))).scalars().all()
    return await _render("admin/org_detail.html", request, title=org.name, org=org, users=users, agents=agents, teams=teams, channels=channels)


@router.get("/admin/orgs/{oid}/suspend")
async def admin_org_suspend(request: Request, oid: str):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    async with db_session() as db:
        org = await db.get(Organization, oid)
        if org:
            org.is_active = False
            await db.commit()
    return RedirectResponse("/dashboard/admin", status_code=303)


@router.get("/admin/orgs/{oid}/unsuspend")
async def admin_org_unsuspend(request: Request, oid: str):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    async with db_session() as db:
        org = await db.get(Organization, oid)
        if org:
            org.is_active = True
            await db.commit()
    return RedirectResponse("/dashboard/admin", status_code=303)


@router.get("/admin/orgs/{oid}/users/{uid}/remove")
async def admin_remove_user(request: Request, oid: str, uid: str):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    async with db_session() as db:
        user = await db.get(User, uid)
        if user and user.org_id == oid and user.role != "superadmin":
            await db.delete(user)
            await db.commit()
    return RedirectResponse(f"/dashboard/admin/orgs/{oid}", status_code=303)


# ─── Fleet management ───

@router.get("/admin/fleet", response_class=HTMLResponse)
async def admin_fleet(request: Request):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    from aios.db.models import RemoteInstance
    async with db_session() as db:
        instances = (await db.execute(select(RemoteInstance).order_by(RemoteInstance.name))).scalars().all()
    return await _render("admin/fleet.html", request, title="Frota de Clientes", instances=instances)


@router.post("/admin/fleet/add")
async def admin_fleet_add(
    request: Request,
    name: str = Form(...), base_url: str = Form(...),
    api_key: str = Form(""), client_org_id: str = Form(""),
):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    from aios.db.models import RemoteInstance
    async with db_session() as db:
        inst = RemoteInstance(
            org_id=await _org_filter(request),
            name=name, base_url=base_url.rstrip("/"),
            api_key=api_key, client_org_id=client_org_id,
            extra_data={},
        )
        db.add(inst)
        await db.flush()
        # test connectivity
        try:
            import httpx
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base_url}/api/admin/health", headers=headers)
                if resp.status_code == 200:
                    inst.extra_data["health"] = resp.json()
                    inst.is_active = True
        except Exception as e:
            logger.exception("Fleet health check failed")
            inst.extra_data.setdefault("errors", []).append(str(e))
        await db.commit()
    return RedirectResponse("/dashboard/admin/fleet", status_code=303)


@router.get("/admin/fleet/{fid}", response_class=HTMLResponse)
async def admin_fleet_view(request: Request, fid: str):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    from aios.db.models import RemoteInstance
    async with db_session() as db:
        inst = await db.get(RemoteInstance, fid)
        if not inst:
            return HTMLResponse("<h2>Não encontrado</h2>", status_code=404)

        # proxy to client instance for live data
        agents = []
        teams = []
        conversations = []
        health = inst.extra_data.get("health", {})
        try:
            import httpx
            headers = {}
            if inst.api_key:
                headers["Authorization"] = f"Bearer {inst.api_key}"
            async with httpx.AsyncClient(timeout=15) as client:
                health_resp = await client.get(f"{inst.base_url}/api/admin/health", headers=headers)
                if health_resp.status_code == 200:
                    health = health_resp.json()
                    inst.extra_data["health"] = health
                    await db.commit()

                agents_resp = await client.get(f"{inst.base_url}/api/agents", headers=headers)
                if agents_resp.status_code == 200:
                    agents = agents_resp.json()

                teams_resp = await client.get(f"{inst.base_url}/api/teams", headers=headers)
                if teams_resp.status_code == 200:
                    teams = teams_resp.json()
        except Exception as e:
            logger.exception("Fleet proxy request failed")
            inst.extra_data["error"] = str(e)

    return await _render("admin/client_view.html", request, title=inst.name,
                   instance=inst, agents=agents, teams=teams,
                   conversations=conversations, health=health)


@router.get("/admin/fleet/{fid}/open")
async def admin_fleet_open(fid: str):
    from aios.db.models import RemoteInstance
    async with db_session() as db:
        inst = await db.get(RemoteInstance, fid)
        if not inst:
            return HTMLResponse("<h2>Não encontrado</h2>", status_code=404)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(inst.base_url)


@router.get("/admin/fleet/{fid}/remove")
async def admin_fleet_remove(fid: str):
    from aios.db.models import RemoteInstance
    async with db_session() as db:
        inst = await db.get(RemoteInstance, fid)
        if inst:
            await db.delete(inst)
            await db.commit()
    return RedirectResponse("/dashboard/admin/fleet", status_code=303)


# ─── Dead Letter Queue Admin ───

@router.get("/admin/dlq", response_class=HTMLResponse)
async def admin_dlq(request: Request, limit: int = 50, org_filter: str = ""):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    from aios.core.dead_letter import list_dlq
    entries = await list_dlq(limit)
    if org_filter:
        entries = [e for e in entries if e.get("org_id") == org_filter]
    from aios.db.models import Organization
    async with db_session() as db:
        orgs = (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
    return await _render("admin/dlq.html", request, title="Dead Letter Queue", entries=entries, orgs=orgs, org_filter=org_filter, limit=limit)


@router.post("/admin/dlq/{entry_id}/retry")
async def admin_dlq_retry(request: Request, entry_id: str):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    from aios.core.dead_letter import retry_dlq
    result = await retry_dlq(entry_id)
    if not result["ok"]:
        return HTMLResponse("Entrada não encontrada", status_code=404)
    return RedirectResponse("/dashboard/admin/dlq", status_code=303)


@router.post("/admin/dlq/{entry_id}/delete")
async def admin_dlq_delete(request: Request, entry_id: str):
    denied = await _require_superadmin(request)
    if denied and isinstance(denied, HTMLResponse):
        return denied
    from aios.db.models import DeadLetter
    async with db_session() as db:
        entry = await db.get(DeadLetter, entry_id)
        if entry:
            await db.delete(entry)
            await db.commit()
    return RedirectResponse("/dashboard/admin/dlq", status_code=303)


# ─── Billing page ───

@router.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    from aios.config import PLANS
    org_id = await _org_filter(request)
    async with db_session() as db:
        org = await db.get(Organization, org_id)
        agent_count = (await db.execute(select(func.count(Agent.id)).where(Agent.org_id == org_id))).scalar() or 0
        team_count = (await db.execute(select(func.count(Team.id)).where(Team.org_id == org_id))).scalar() or 0
    current_plan = org.extra_data.get("plan", "free") if org else "free"
    plan_limits = PLANS.get(current_plan, PLANS["free"])

    from aios.core.limits import get_usage_summary, get_monthly_usage, get_agent_usage_breakdown
    async with db_session() as db:
        usage = await get_usage_summary(org_id, db)
        monthly = await get_monthly_usage(org_id, db)
        agent_breakdown = await get_agent_usage_breakdown(org_id, db)
        # model breakdown inline
        from sqlalchemy import select as _select
        from aios.db.models import AgentMetric, Agent as _Agent

        rows = (await db.execute(_select(AgentMetric).where(AgentMetric.org_id == org_id).order_by(AgentMetric.hour.desc()).limit(200))).scalars().all()
        model_map: dict = {}
        if rows:
            aids = list({r.agent_id for r in rows})
            agents_q = (await db.execute(_select(_Agent).where(_Agent.id.in_(aids)))).scalars().all()
            amap = {a.id: a.llm_config.get("model", "openai/gpt-4o-mini") for a in agents_q}
            for r in rows:
                m = amap.get(r.agent_id, "unknown")
                model_map.setdefault(m, {"model": m, "tokens": 0, "cost": 0})
                model_map[m]["tokens"] += r.tokens
                from aios.core.tracing import estimate_cost

                model_map[m]["cost"] += estimate_cost(m, r.tokens)
            for v in model_map.values():
                v["cost"] = round(v["cost"], 4)
        model_breakdown = sorted(model_map.values(), key=lambda x: x["tokens"], reverse=True)
    daily_msgs = usage["messages_today"]

    stripe_prices = {}
    from aios.config import settings
    if settings.stripe_price_starter:
        stripe_prices["starter"] = settings.stripe_price_starter
    if settings.stripe_price_pro:
        stripe_prices["pro"] = settings.stripe_price_pro

    return await _render("billing.html", request, title="Cobrança",
                   current_plan=current_plan, plan_limits=plan_limits,
                   agent_count=agent_count, team_count=team_count,
                   daily_msgs=daily_msgs, monthly=monthly, agent_breakdown=agent_breakdown, model_breakdown=model_breakdown, plans=PLANS,
                   org_id=org_id, stripe_prices=json.dumps(stripe_prices),
                   subscription_id=org.extra_data.get("stripe_subscription_id") if org else None)


@router.get("/promptlab", response_class=HTMLResponse)
async def promptlab_page(request: Request):
    return await _render("promptlab.html", request, title="PromptLab")


# ─── Agent Sandbox (chat playground) ───

@router.get("/sandbox", response_class=HTMLResponse)
async def sandbox_page(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id, Agent.status == "active").order_by(Agent.name))).scalars().all()
    return await _render("sandbox.html", request, title="Sandbox de Agentes", agents=agents)


@router.post("/sandbox/chat")
async def sandbox_chat(
    request: Request,
    agent_id: str = Form(...),
    message: str = Form(...),
    conversation_id: str = Form(""),
):
    """Streaming proxy: agent_id + message → SSE stream of tokens."""
    from aios.core.agent import AgentRuntime

    async def sse_stream():
        org_id = await _org_filter(request)
        async with db_session() as db:
            agent = await db.get(Agent, agent_id)
            if not agent or agent.org_id != org_id:
                yield "data: " + json.dumps({"error": "Agente não encontrado"}) + "\n\n"
                return

            import uuid
            cid = conversation_id or f"sandbox_{uuid.uuid4().hex[:12]}"
            runtime = AgentRuntime(agent, async_session)
            yield "data: " + json.dumps({"conversation_id": cid}) + "\n\n"

            from aios.core.tracing import current_trace_id
            tid = current_trace_id()
            if tid:
                yield "data: " + json.dumps({"type": "trace", "trace_id": tid}) + "\n\n"
            async for event in runtime.run_stream(cid, message, db):
                if event["type"] == "token":
                    yield "data: " + json.dumps({"type": "token", "content": event["content"]}) + "\n\n"
                elif event["type"] == "error":
                    yield "data: " + json.dumps({"type": "error", "error": event.get("error", "")}) + "\n\n"
                elif event["type"] == "tool_call":
                    yield "data: " + json.dumps({"type": "tool_call", "tool_calls": event["tool_calls"]}) + "\n\n"
                elif event["type"] == "done":
                    tid2 = current_trace_id()
                    yield "data: " + json.dumps({"type": "done", "trace_id": tid2}) + "\n\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(sse_stream(), media_type="text/event-stream")


# ─── Files page ───

@router.get("/files", response_class=HTMLResponse)
async def files_list(request: Request):
    org_id = await _org_filter(request)
    from aios.core.storage import list_artifacts
    async with db_session() as db:
        artifacts = await list_artifacts(db, org_id)
    return await _render("files.html", request, title="Arquivos", artifacts=artifacts)


@router.post("/files/upload")
async def files_upload(request: Request):
    org_id = await _org_filter(request)
    from aios.core.storage import save_artifact
    from aios.core.file_validation import validate_file
    form = await request.form()
    file_field = form.get("file")
    if not file_field:
        return RedirectResponse("/dashboard/files", status_code=303)

    content = await file_field.read()
    description = form.get("description", "")

    valid, content_type = validate_file(file_field.filename or "file", bytes(content))
    if not valid:
        return HTMLResponse(f"<h2>Arquivo inválido</h2><p>{content_type}</p><a href='/dashboard/files'>Voltar</a>", status_code=400)

    async with db_session() as db:
        await save_artifact(
            db=db, org_id=org_id,
            filename=file_field.filename or "file",
            content=bytes(content),
            content_type=content_type,
            description=description,
        )
    return RedirectResponse("/dashboard/files", status_code=303)


@router.get("/files/{art_id}/view")
async def files_view(request: Request, art_id: str):
    org_id = await _org_filter(request)
    from aios.core.storage import read_artifact_text
    from aios.db.models import Artifact
    async with db_session() as db:
        art = await db.get(Artifact, art_id)
        if not art or art.org_id != org_id:
            return HTMLResponse("<h2>Não encontrado</h2>", status_code=404)
        text = await read_artifact_text(art_id, db, max_chars=100000)
    return await _render("file_view.html", request, title=art.filename, artifact=art, content=text)


# ─── IDE Lab (Monaco + Tool Runner + Traces) ───

@router.get("/lab", response_class=HTMLResponse)
async def lab_page(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
        artifacts = await __import__("aios.core.storage", fromlist=["list_artifacts"]).list_artifacts(db, org_id)  # type: ignore
        from aios.db.models import Workflow
        wfs = (await db.execute(select(Workflow).where(Workflow.org_id == org_id).order_by(Workflow.created_at.desc()).limit(50))).scalars().all()
    from aios.tools.registry import TOOL_REGISTRY
    tools = [{"name": k, "desc": v.get("description", ""), "schema": v.get("input_schema", {})} for k, v in TOOL_REGISTRY.items()]
    if not tools:
        tools = [
            {"name": "calculator", "desc": "Expressões matemáticas", "schema": {"expression": "string"}},
            {"name": "web_search", "desc": "Buscar na web", "schema": {"query": "string"}},
            {"name": "http_get", "desc": "Buscar URLs HTTPS", "schema": {"url": "string"}},
            {"name": "current_datetime", "desc": "Hora atual", "schema": {"timezone": "string"}},
            {"name": "send_email", "desc": "Enviar e-mail", "schema": {"to": "string", "subject": "string", "body": "string"}},
            {"name": "read_file", "desc": "Ler arquivo por ID", "schema": {"artifact_id": "string"}},
        ]
    return await _render("lab.html", request, title="Lab — IDE leve", agents=agents, tools=tools, artifacts=artifacts, workflows=wfs)


@router.post("/lab/tool-run")
async def lab_tool_run(request: Request):
    from fastapi.responses import JSONResponse
    import json as _json
    try:
        body = await request.json()
    except Exception:
        form = await request.form()
        body = dict(form)
    tool_name = (body.get("tool") or body.get("tool_name") or "").strip()
    raw_args = body.get("args") or body.get("arguments") or "{}"
    if isinstance(raw_args, dict):
        raw_args = _json.dumps(raw_args)
    if not tool_name:
        return JSONResponse({"error": "tool required"}, status_code=400)
    from aios.core.tools import ToolEngine
    from aios.tools.registry import TOOL_REGISTRY
    if tool_name not in TOOL_REGISTRY:
        return JSONResponse({"error": f"tool '{tool_name}' not registered"}, status_code=404)
    eng = ToolEngine([tool_name])
    try:
        out = await eng.execute(tool_name, raw_args if isinstance(raw_args, str) else _json.dumps(raw_args))
        return JSONResponse({"ok": True, "tool": tool_name, "output": out})
    except Exception as e:
        return JSONResponse({"ok": False, "tool": tool_name, "error": str(e)}, status_code=200)


@router.get("/lab/traces/{trace_id}")
async def lab_trace_proxy(request: Request, trace_id: str):
    from fastapi.responses import JSONResponse
    from aios.core.tracing import get_trace, TRACES
    if trace_id == "recent":
        recent = [{"key": k, "trace_id": v.trace_id, "span_type": v.span_type, "model": v.model, "duration_ms": round((v.end - v.start)*1000,1) if v.end else 0}
                  for k, v in list(TRACES.items())[-30:]]
        return JSONResponse({"trace_id": "recent", "spans": [], "recent": recent})
    spans = get_trace(trace_id)
    if not spans:
        recent = [{"key": k, "trace_id": v.trace_id, "span_type": v.span_type, "model": v.model, "duration_ms": round((v.end - v.start)*1000,1) if v.end else 0}
                  for k, v in list(TRACES.items())[-30:]]
        return JSONResponse({"trace_id": trace_id, "spans": [], "recent": recent})
    return JSONResponse({"trace_id": trace_id, "spans": spans})


@router.get("/lab/workflows")
async def lab_workflows(request: Request):
    org_id = await _org_filter(request)
    from fastapi.responses import JSONResponse
    from aios.db.models import Workflow
    async with db_session() as db:
        wfs = (await db.execute(select(Workflow).where(Workflow.org_id == org_id).order_by(Workflow.created_at.desc()))).scalars().all()
        return JSONResponse([{"id": w.id, "name": w.name, "status": w.status, "timeout_seconds": w.timeout_seconds} for w in wfs])


@router.post("/lab/workflows")
async def lab_workflow_create(request: Request):
    org_id = await _org_filter(request)
    from fastapi.responses import JSONResponse
    from aios.db.models import Workflow
    form = await request.form()
    name = form.get("name") or "Workflow"
    desc = form.get("description") or ""
    async with db_session() as db:
        wf = Workflow(org_id=org_id, name=name, description=desc)
        db.add(wf)
        await db.commit()
        await db.refresh(wf)
        return JSONResponse({"id": wf.id, "name": wf.name})
    return JSONResponse({"ok": True})


@router.get("/lab/agents/{agent_id}/versions")
async def lab_agent_versions(request: Request, agent_id: str):
    org_id = await _org_filter(request)
    from fastapi.responses import JSONResponse
    from aios.db.models import Agent, AgentVersion
    async with db_session() as db:
        ag = await db.get(Agent, agent_id)
        if not ag or ag.org_id != org_id:
            return JSONResponse({"error": "not found"}, status_code=404)
        vers = (await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()).limit(20))).scalars().all()
        return JSONResponse([{"id": v.id, "version": v.version, "name": v.name, "change_note": v.change_note, "created_at": str(v.created_at)} for v in vers])


@router.post("/lab/agents/{agent_id}/publish")
async def lab_agent_publish(request: Request, agent_id: str):
    org_id = await _org_filter(request)
    from fastapi.responses import JSONResponse
    from aios.db.models import Agent, AgentVersion, Dataset, EvalRun
    from sqlalchemy import func as _func, select
    import json
    import time

    form = await request.form()
    note = form.get("note") or ""
    judge_model = form.get("judge_model") or "openai/gpt-4o-mini"

    async with db_session() as db:
        ag = await db.get(Agent, agent_id)
        if not ag or ag.org_id != org_id:
            return JSONResponse({"error": "not found"}, status_code=404)
        max_v = (await db.execute(select(_func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent_id))).scalar() or 0
        v = AgentVersion(agent_id=ag.id, org_id=org_id, version=max_v + 1, name=ag.name, system_prompt=ag.system_prompt, llm_config=dict(ag.llm_config or {}), tools=list(ag.tools or []), memory_config=dict(ag.memory_config or {}), governance_config=dict(ag.governance_config or {}), agent_type=ag.agent_type, change_note=note)
        db.add(v)
        await db.commit()

        # avaliação real: se dataset existe, roda eval com juiz gpt-4o-mini
        ds = (await db.execute(select(Dataset).where(Dataset.agent_id == agent_id).limit(1))).scalars().first()
        eval_triggered = False
        eval_results = []
        avg_score = 0.0

        if ds and ds.cases:
            eval_triggered = True
            from aios.core.agent import AgentRuntime
            from aios.core.providers import get_provider

            runtime = AgentRuntime(ag)
            results = []
            cases = ds.cases[:20]  # limite 20 casos

            for case in cases:
                start = time.time()
                inp = case.get("input", "") if isinstance(case, dict) else str(case)
                expected = case.get("expected") if isinstance(case, dict) else None
                try:
                    out = await runtime.run(f"eval_{agent_id}", inp, db)
                except Exception as e:
                    out = f"ERROR: {e}"
                latency = int((time.time() - start) * 1000)

                score = None
                if expected:
                    try:
                        judge = get_provider(judge_model)
                        resp = await judge.chat_retry(
                            messages=[
                                {
                                    "role": "system",
                                    "content": 'Score 0-1 whether output matches expected. Return JSON {"score":0.0-1.0}',
                                },
                                {
                                    "role": "user",
                                    "content": f"Expected: {expected}\nOutput: {out[:2000]}",
                                },
                            ],
                            model=judge_model,
                            temperature=0.0,
                            max_tokens=100,
                        )
                        txt = resp.get("content", "")
                        score = float(json.loads(txt).get("score", 0)) if "{" in txt else 0.0
                    except (ValueError, json.JSONDecodeError, KeyError):
                        score = 1.0 if expected.lower() in out.lower() else 0.0

                results.append({
                    "input": inp,
                    "output": out[:4000],
                    "expected": expected,
                    "score": score,
                    "latency_ms": latency,
                })

            # calcular média
            valid_scores = [r["score"] for r in results if r["score"] is not None]
            avg_score = round(sum(valid_scores) / max(1, len(valid_scores)), 3) if valid_scores else 0.0
            eval_results = results

        # persistir EvalRun
        try:
            er = EvalRun(
                agent_id=agent_id,
                org_id=org_id,
                dataset_id=ds.id if ds else None,
                version_id=v.id,
                judge_model=judge_model,
                avg_score=avg_score,
                results=eval_results,
                extra_data={"auto": True}
            )
            db.add(er)
            await db.commit()
        except Exception:
            pass

        return JSONResponse({
            "ok": True,
            "version": v.version,
            "eval_triggered": eval_triggered,
            "eval_run_id": er.id if 'er' in locals() and er.id else None,
            "avg_score": avg_score,
            "case_count": len(eval_results)
        })


@router.get("/lab/artifacts/{art_id}/raw")
async def lab_artifact_raw(request: Request, art_id: str):
    org_id = await _org_filter(request)
    from aios.core.storage import read_artifact_text, get_artifact_content
    from aios.db.models import Artifact
    from fastapi.responses import JSONResponse
    async with db_session() as db:
        art = await db.get(Artifact, art_id)
        if not art or art.org_id != org_id:
            return JSONResponse({"error": "not found"}, status_code=404)
        text = await read_artifact_text(art_id, db, max_chars=20000)
        raw = await get_artifact_content(art_id, db, org_id=org_id)
        return JSONResponse({"id": art.id, "filename": art.filename, "content_type": art.content_type, "size_bytes": art.size_bytes, "text": text[:20000], "is_binary": raw is not None and len(raw) > 0 and text.startswith("Binary file")})


# ─── Automations (no-code workflows sem n8n) ───

@router.get("/automations", response_class=HTMLResponse)
async def automations_list(request: Request, filter: str = "all"):
    org_id = await _org_filter(request)
    from aios.db.models import Workflow, AutomationTrigger, WorkflowRun, Credential
    from aios.api.automations import AUTOMATION_TEMPLATES
    async with db_session() as db:
        wfs = (await db.execute(select(Workflow).where(Workflow.org_id == org_id).order_by(Workflow.created_at.desc()))).scalars().all()
        trigs = (await db.execute(select(AutomationTrigger).where(AutomationTrigger.org_id == org_id))).scalars().all()
        triggers_map = {}
        for t in trigs:
            triggers_map.setdefault(t.workflow_id, []).append(t)
        # filter
        if filter != "all":
            if filter in ("webhook","cron","event"):
                wfs = [w for w in wfs if any(t.type==filter for t in triggers_map.get(w.id,[]))]
            elif filter == "failed":
                failed_ids = set((await db.execute(select(WorkflowRun.workflow_id).where(WorkflowRun.org_id==org_id, WorkflowRun.status=="failed"))).scalars().all())
                wfs = [w for w in wfs if w.id in failed_ids]
        runs_map = {}
        for w in wfs:
            last = (await db.execute(select(WorkflowRun).where(WorkflowRun.workflow_id==w.id).order_by(WorkflowRun.created_at.desc()).limit(1))).scalars().first()
            if last:
                runs_map[w.id] = last
        recent_runs = (await db.execute(select(WorkflowRun).where(WorkflowRun.org_id==org_id).order_by(WorkflowRun.created_at.desc()).limit(20))).scalars().all()
        creds = (await db.execute(select(Credential).where(Credential.org_id==org_id))).scalars().all()
        runs_today = sum(1 for r in recent_runs if r.created_at and (datetime.now(timezone.utc).replace(tzinfo=None) - r.created_at).days == 0)
        failed_count = sum(1 for r in recent_runs if r.status=="failed")
        active_count = sum(1 for t in trigs if t.is_active)
    return await _render("automations.html", request, title="Automações", workflows=wfs, triggers=trigs, triggers_map=triggers_map, runs_map=runs_map, recent_runs=recent_runs, credentials=creds, templates=AUTOMATION_TEMPLATES, filter=filter, active_count=active_count, runs_today=runs_today, failed_count=failed_count)

@router.get("/automations/{wf_id}", response_class=HTMLResponse)
async def automation_detail(request: Request, wf_id: str):
    org_id = await _org_filter(request)
    from aios.db.models import Workflow, WorkflowNode, AutomationTrigger, WorkflowRun
    async with db_session() as db:
        wf = await db.get(Workflow, wf_id)
        if not wf or wf.org_id != org_id:
            return HTMLResponse("<h2>Não encontrado</h2>", status_code=404)
        nodes = (await db.execute(select(WorkflowNode).where(WorkflowNode.workflow_id==wf_id).order_by(WorkflowNode.created_at))).scalars().all()
        triggers = (await db.execute(select(AutomationTrigger).where(AutomationTrigger.workflow_id==wf_id))).scalars().all()
        runs = (await db.execute(select(WorkflowRun).where(WorkflowRun.workflow_id==wf_id).order_by(WorkflowRun.created_at.desc()).limit(20))).scalars().all()
        agents = (await db.execute(select(Agent).where(Agent.org_id==org_id).order_by(Agent.name))).scalars().all()
    return await _render("automation_detail.html", request, title=wf.name, wf=wf, nodes=nodes, triggers=triggers, runs=runs, agents=agents, last_result=request.query_params.get("result",""))

@router.post("/automations/create")
async def automations_create(request: Request):
    org_id = await _org_filter(request)
    form = await request.form()
    name = form.get("name") or "Automação"
    desc = form.get("description") or ""
    ttype = form.get("trigger_type") or "webhook"
    tval = form.get("trigger_value") or ""
    from aios.db.models import Workflow, AutomationTrigger
    import uuid
    async with db_session() as db:
        wf = Workflow(org_id=org_id, name=name, description=desc, timeout_seconds=120)
        db.add(wf)
        await db.flush()
        if ttype == "webhook":
            db.add(AutomationTrigger(workflow_id=wf.id, org_id=org_id, type="webhook", name="Webhook", config={}, webhook_path=f"wh_{uuid.uuid4().hex[:16]}", is_active=True))
        elif ttype == "cron":
            cron_expr = tval or "0 9 * * *"
            trig = AutomationTrigger(workflow_id=wf.id, org_id=org_id, type="cron", name="Agendamento", config={}, cron_expr=cron_expr, is_active=True)
            try:
                from croniter import croniter
                trig.next_run_at = croniter(cron_expr, datetime.now(timezone.utc)).get_next(datetime)
            except Exception:
                pass
            db.add(trig)
        elif ttype == "event":
            db.add(AutomationTrigger(workflow_id=wf.id, org_id=org_id, type="event", name="Evento", config={}, event_type=tval or "message.received", is_active=True))
        await db.commit()
        await db.refresh(wf)
    return RedirectResponse(f"/dashboard/automations/{wf.id}", status_code=303)

@router.post("/automations/from-template/{tid}")
async def automations_from_template(request: Request, tid: str):
    org_id = await _org_filter(request)
    from aios.api.automations import AUTOMATION_TEMPLATES
    tpl = AUTOMATION_TEMPLATES.get(tid)
    if not tpl:
        return RedirectResponse("/dashboard/automations", status_code=303)
    from aios.db.models import Workflow, WorkflowNode, AutomationTrigger
    import uuid
    async with db_session() as db:
        wf = Workflow(org_id=org_id, name=tpl["name"], description=tpl["description"], timeout_seconds=120)
        db.add(wf)
        await db.flush()
        prev_id = None
        for nd in tpl.get("nodes", []):
            deps = [prev_id] if nd.get("depends_on")==["__prev__"] and prev_id else []
            node = WorkflowNode(workflow_id=wf.id, label=nd.get("label",""), tool_name=nd.get("tool_name"), tool_args=nd.get("tool_args",{}), depends_on=deps, condition=nd.get("condition"), output_key=nd.get("output_key","result"))
            db.add(node)
            await db.flush()
            prev_id = node.id
        trig = tpl.get("trigger", {})
        ttype = trig.get("type","webhook")
        if ttype == "webhook":
            db.add(AutomationTrigger(workflow_id=wf.id, org_id=org_id, type="webhook", name=trig.get("name",""), config={}, webhook_path=f"wh_{uuid.uuid4().hex[:16]}", is_active=True))
        elif ttype == "cron":
            cron_expr = trig.get("cron","0 9 * * *")
            tr = AutomationTrigger(workflow_id=wf.id, org_id=org_id, type="cron", name=trig.get("name",""), config={}, cron_expr=cron_expr, is_active=True)
            try:
                from croniter import croniter
                tr.next_run_at = croniter(cron_expr, datetime.now(timezone.utc)).get_next(datetime)
            except Exception:
                pass
            db.add(tr)
        await db.commit()
        await db.refresh(wf)
    return RedirectResponse(f"/dashboard/automations/{wf.id}", status_code=303)

@router.post("/automations/{wf_id}/trigger")
async def automations_add_trigger(request: Request, wf_id: str):
    org_id = await _org_filter(request)
    form = await request.form()
    ttype = form.get("type") or "webhook"
    name = form.get("name") or ""
    val = form.get("value") or ""
    from aios.db.models import Workflow, AutomationTrigger
    import uuid
    async with db_session() as db:
        wf = await db.get(Workflow, wf_id)
        if not wf or wf.org_id != org_id:
            return RedirectResponse("/dashboard/automations", status_code=303)
        if ttype == "webhook":
            db.add(AutomationTrigger(workflow_id=wf_id, org_id=org_id, type="webhook", name=name, config={}, webhook_path=f"wh_{uuid.uuid4().hex[:16]}", is_active=True))
        elif ttype == "cron":
            cron_expr = val or "0 9 * * *"
            tr = AutomationTrigger(workflow_id=wf_id, org_id=org_id, type="cron", name=name, config={}, cron_expr=cron_expr, is_active=True)
            try:
                from croniter import croniter
                tr.next_run_at = croniter(cron_expr, datetime.now(timezone.utc)).get_next(datetime)
            except Exception:
                pass
            db.add(tr)
        else:
            db.add(AutomationTrigger(workflow_id=wf_id, org_id=org_id, type="event", name=name, config={}, event_type=val, is_active=True))
        await db.commit()
    return RedirectResponse(f"/dashboard/automations/{wf_id}", status_code=303)

@router.get("/automations/{wf_id}/trigger/{tid}/toggle")
async def automations_toggle_trigger(request: Request, wf_id: str, tid: str):
    org_id = await _org_filter(request)
    from aios.db.models import AutomationTrigger
    async with db_session() as db:
        tr = await db.get(AutomationTrigger, tid)
        if tr and tr.org_id == org_id:
            tr.is_active = not tr.is_active
            await db.commit()
    return RedirectResponse(f"/dashboard/automations/{wf_id}", status_code=303)

@router.get("/automations/{wf_id}/trigger/{tid}/delete")
async def automations_delete_trigger(request: Request, wf_id: str, tid: str):
    org_id = await _org_filter(request)
    from aios.db.models import AutomationTrigger
    async with db_session() as db:
        tr = await db.get(AutomationTrigger, tid)
        if tr and tr.org_id == org_id:
            await db.delete(tr)
            await db.commit()
    return RedirectResponse(f"/dashboard/automations/{wf_id}", status_code=303)

@router.post("/automations/{wf_id}/node")
async def automations_add_node(request: Request, wf_id: str):
    org_id = await _org_filter(request)
    form = await request.form()
    label = form.get("label") or ""
    tool_val = form.get("tool_name") or ""
    deps_raw = form.get("depends_on") or ""
    from aios.db.models import Workflow, WorkflowNode
    async with db_session() as db:
        wf = await db.get(Workflow, wf_id)
        if not wf or wf.org_id != org_id:
            return RedirectResponse("/dashboard/automations", status_code=303)
        agent_id = None
        tool_name = None
        if tool_val.startswith("agent:"):
            agent_id = tool_val.split(":",1)[1]
        elif tool_val:
            tool_name = tool_val
        # resolve depends_on by label or id
        depends = []
        if deps_raw.strip():
            all_nodes = (await db.execute(select(WorkflowNode).where(WorkflowNode.workflow_id==wf_id))).scalars().all()
            label_map = {n.label: n.id for n in all_nodes if n.label}
            for part in deps_raw.split(","):
                part=part.strip()
                if not part:
                    continue
                depends.append(label_map.get(part, part))
        default_args = {}
        if tool_name == "http_request":
            default_args = {"url": "https://httpbin.org/post", "method": "POST", "body": {"msg": "hello {{json.input}}"}, "headers": {}}
        elif tool_name == "wait":
            default_args = {"seconds": 2}
        elif tool_name == "transform":
            default_args = {"input": {"raw": "{{json}}"}, "mapping": {"msg": "valor {{input.raw}}"} }
        elif tool_name == "code":
            default_args = {"code": "output = {'echo': input_data}", "input_data": {}}
        elif tool_name == "if_branch":
            default_args = {"condition": "input.get('valor',0) > 10", "input": {"valor": 5}}
        node = WorkflowNode(workflow_id=wf_id, label=label, agent_id=agent_id, tool_name=tool_name, tool_args=default_args, depends_on=depends, output_key="result")
        db.add(node)
        await db.commit()
    return RedirectResponse(f"/dashboard/automations/{wf_id}", status_code=303)

@router.post("/automations/{wf_id}/node/{nid}/delete")
async def automations_delete_node(request: Request, wf_id: str, nid: str):
    org_id = await _org_filter(request)
    from aios.db.models import Workflow, WorkflowNode
    async with db_session() as db:
        wf = await db.get(Workflow, wf_id)
        nd = await db.get(WorkflowNode, nid)
        if wf and nd and wf.org_id == org_id and nd.workflow_id == wf_id:
            await db.delete(nd)
            await db.commit()
    return RedirectResponse(f"/dashboard/automations/{wf_id}", status_code=303)

@router.post("/automations/{wf_id}/run")
async def automations_run(request: Request, wf_id: str):
    org_id = await _org_filter(request)
    form = await request.form()
    inp = form.get("input") or form.get("message") or "{}"
    from aios.db.models import Workflow, WorkflowRun
    from sqlalchemy.orm import selectinload
    async with db_session() as db:
        wf = await db.get(Workflow, wf_id, options=[selectinload(Workflow.nodes)])
        if not wf or wf.org_id != org_id:
            return RedirectResponse("/dashboard/automations", status_code=303)
        run = WorkflowRun(workflow_id=wf_id, org_id=org_id, status="pending", inputs={"input": inp})
        db.add(run)
        await db.commit()
        await db.refresh(run)
        try:
            from aios.tasks.queue import enqueue_job
            await enqueue_job("aios.tasks.jobs.workflow_run_job", {"workflow_id": wf_id, "run_id": run.id})
        except Exception:
            from aios.core.workflow import WorkflowDef, WorkflowNode as WNode, WorkflowEngine
            wdef = WorkflowDef(id=wf.id, name=wf.name, timeout=wf.timeout_seconds)
            for n in wf.nodes:
                wdef.nodes[n.id] = WNode(id=n.id, agent_id=n.agent_id, tool_name=n.tool_name, tool_args=n.tool_args or {}, depends_on=n.depends_on or [], condition=n.condition, output_key=n.output_key, timeout=n.timeout_seconds)
            eng = WorkflowEngine()
            res = await eng.run(wdef, run.id, inp)
            run.status = "done" if res.ok() else "failed"
            run.outputs = res.outputs
            run.node_status = res.node_status
            if res.errors:
                run.error = str(res.errors)[:2000]
            await db.commit()
    return RedirectResponse(f"/dashboard/automations/{wf_id}?result=ok", status_code=303)

@router.post("/automations/{wf_id}/duplicate")
async def automations_duplicate(request: Request, wf_id: str):
    org_id = await _org_filter(request)
    from aios.db.models import Workflow, WorkflowNode
    async with db_session() as db:
        wf = await db.get(Workflow, wf_id)
        if not wf or wf.org_id != org_id:
            return RedirectResponse("/dashboard/automations", status_code=303)
        nodes = (await db.execute(select(WorkflowNode).where(WorkflowNode.workflow_id==wf_id))).scalars().all()
        new_wf = Workflow(org_id=org_id, name=wf.name+" (cópia)", description=wf.description, timeout_seconds=wf.timeout_seconds)
        db.add(new_wf)
        await db.flush()
        id_map = {}
        for n in nodes:
            nn = WorkflowNode(workflow_id=new_wf.id, label=n.label, agent_id=n.agent_id, tool_name=n.tool_name, tool_args=dict(n.tool_args or {}), depends_on=[], condition=n.condition, output_key=n.output_key, timeout_seconds=n.timeout_seconds, position=dict(n.position or {}))
            db.add(nn)
            await db.flush()
            id_map[n.id] = nn.id
        # fix deps
        for n in nodes:
            if n.depends_on:
                nn_id = id_map[n.id]
                nn = await db.get(WorkflowNode, nn_id)
                nn.depends_on = [id_map.get(d, d) for d in n.depends_on]
        await db.commit()
    return RedirectResponse("/dashboard/automations", status_code=303)

@router.get("/automations/{wf_id}/delete")
async def automations_delete(request: Request, wf_id: str):
    org_id = await _org_filter(request)
    from aios.db.models import Workflow
    async with db_session() as db:
        wf = await db.get(Workflow, wf_id)
        if wf and wf.org_id == org_id:
            await db.delete(wf)
            await db.commit()
    return RedirectResponse("/dashboard/automations", status_code=303)

@router.get("/automations/{wf_id}/compare")
async def automations_compare(request: Request, wf_id: str, run1: str = "", run2: str = ""):
    org_id = await _org_filter(request)
    from aios.db.models import WorkflowRun
    async with db_session() as db:
        r1 = await db.get(WorkflowRun, run1) if run1 else None
        r2 = await db.get(WorkflowRun, run2) if run2 else None
        return await _render("automation_compare.html", request, title="Comparar", r1=r1, r2=r2, wf_id=wf_id)

@router.get("/automations/{wf_id}/run/{run_id}")
async def automations_run_detail(request: Request, wf_id: str, run_id: str):
    org_id = await _org_filter(request)
    from aios.db.models import WorkflowRun
    async with db_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run or run.org_id != org_id:
            return HTMLResponse("<h2>Não encontrado</h2>", status_code=404)
        return await _render("automation_run.html", request, title="Execução", run=run)

@router.post("/automations/credentials")
async def automations_cred_create(request: Request):
    org_id = await _org_filter(request)
    form = await request.form()
    name = form.get("name") or ""
    ctype = form.get("cred_type") or "bearer"
    val = form.get("value") or ""
    if not name or not val:
        return RedirectResponse("/dashboard/automations", status_code=303)
    from aios.db.models import Credential
    from aios.core.secrets import encrypt_secret
    import json
    async with db_session() as db:
        data = {"value": val, "token": val, "key": val}
        enc = encrypt_secret(json.dumps(data))
        db.add(Credential(org_id=org_id, name=name, cred_type=ctype, data_enc=enc))
        await db.commit()
    return RedirectResponse("/dashboard/automations", status_code=303)

@router.get("/automations/credentials/{cid}/delete")
async def automations_cred_delete(request: Request, cid: str):
    org_id = await _org_filter(request)
    from aios.db.models import Credential
    async with db_session() as db:
        c = await db.get(Credential, cid)
        if c and c.org_id == org_id:
            await db.delete(c)
            await db.commit()
    return RedirectResponse("/dashboard/automations", status_code=303)

@router.get("/wizard", response_class=HTMLResponse)
async def wizard_page(request: Request):
    return await _render("wizard.html", request, title="Assistente 60s")

@router.get("/dev", response_class=HTMLResponse)
async def dev_page(request: Request):
    return await _render("dev.html", request, title="Dev Claude+Codex")

@router.get("/proposal", response_class=HTMLResponse)
async def proposal_page(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        from aios.db.models import Organization
        from aios.core.limits import get_monthly_usage
        org = await db.get(Organization, org_id)
        monthly = await get_monthly_usage(org_id, db)
        from sqlalchemy import func as _func2
        from aios.db.models import Agent as _Ag2
        agent_count = (await db.execute(select(func.count(_Ag2.id)).where(_Ag2.org_id == org_id))).scalar() or 0
        economia = int(monthly["total_messages"] * 1.25) or 1200
        return await _render("proposal.html", request, title="Proposta", org=org, date=__import__("datetime").date.today().isoformat(), economia=economia, msgs=monthly["total_messages"], cost=monthly["total_cost"], roi="8", plan=monthly["plan"], agents=agent_count, channels="whatsapp")

@router.post("/billing/trial")
async def billing_trial(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        from aios.db.models import Organization
        org = await db.get(Organization, org_id)
        if org:
            data = dict(org.extra_data or {})
            if data.get("trial_used"):
                return RedirectResponse("/dashboard/billing?error=trial_used", status_code=303)
            import datetime as _dt
            data["plan"] = "pro"
            data["trial"] = True
            data["trial_until"] = (_dt.date.today() + _dt.timedelta(days=14)).isoformat()
            data["trial_used"] = True
            org.extra_data = data
            await db.commit()
    return RedirectResponse("/dashboard/billing?trial=ok", status_code=303)

@router.post("/wizard/create")
async def wizard_create(request: Request, phone: str = Form(...), vertical: str = Form("support")):
    org_id = await _org_filter(request)
    from aios.templates import apply_template
    from aios.db.models import Agent, ChannelConnection
    from aios.core.secrets import encrypt_channel_config
    from aios.config import settings
    import re as _re, uuid as _uuid
    if not _re.match(r"^\d{10,15}$", phone):
        return await _render("wizard.html", request, title="Assistente 60s", error="WhatsApp inválido: use 5511999999999 (10-15 dígitos)")
    # cria agente do vertical
    tpl_map = {"clinica": "support", "imobiliaria": "sdr", "ecommerce": "support"}
    atype = tpl_map.get(vertical, vertical)
    tpl = apply_template(atype) if atype in ["sdr","support","closer","manager"] else apply_template("support")
    async with db_session() as db:
        ag = Agent(org_id=org_id, name=f"Bot {vertical.capitalize()}", agent_type=atype, system_prompt=tpl.get("system_prompt",""), llm_config=tpl.get("llm_config",{}), tools=tpl.get("tools",[]), memory_config=tpl.get("memory_config",{}))
        db.add(ag)
        await db.flush()
        # cria instância evolution com uuid para evitar colisão
        from aios.core.evolution_api import evo_create_instance
        inst_name = f"wizard{_uuid.uuid4().hex[:6]}"
        try:
            await evo_create_instance(inst_name)
        except Exception:
            pass
        ch = ChannelConnection(org_id=org_id, label=f"WhatsApp {phone}", channel_type="evolution", config=encrypt_channel_config({"server_url": settings.evolution_server_url, "api_key": settings.evolution_api_key, "instance": inst_name}), agent_id=ag.id, is_active=True)
        db.add(ch)
        await db.commit()
    return RedirectResponse(f"/dashboard/evolution", status_code=303)

@router.get("/crm", response_class=HTMLResponse)
async def crm_page(request: Request, q: str = "", agent_id: str = ""):
    org_id = await _org_filter(request)
    from aios.db.models import CrmDeal, Organization, Agent as _Ag, PendingAction
    async with db_session() as db:
        org = await db.get(Organization, org_id)
        crm_enabled = False
        if org:
            d = org.extra_data or {}
            crm_enabled = d.get("crm_enabled") or d.get("plan") in ("unlimited","enterprise") or (d.get("trial") and d.get("plan")=="pro")
            # monitoramas superadmin tem sempre
            from aios.api.deps import get_dashboard_user
            try:
                u = await get_dashboard_user(request)
                if u and u.role=="superadmin":
                    crm_enabled = True
            except Exception:
                pass
        deals = []
        stats = {"total":0,"by_stage":{s:0 for s in ["prospection","mql","sql","opportunity","closed_won","closed_lost"]},"total_value":0,"total_cost":0,"total_cost_brl":0}
        pending = []
        agents = (await db.execute(select(_Ag).where(_Ag.org_id==org_id).order_by(_Ag.name))).scalars().all()
        if crm_enabled:
            query = select(CrmDeal).where(CrmDeal.org_id==org_id)
            if agent_id:
                query = query.where(CrmDeal.agent_id==agent_id)
            if q:
                query = query.where((CrmDeal.lead_name.ilike(f"%{q}%")) | (CrmDeal.lead_email.ilike(f"%{q}%")))
            deals = (await db.execute(query.order_by(CrmDeal.updated_at.desc()).limit(100))).scalars().all()
            for d in deals:
                stats["by_stage"][d.stage] = stats["by_stage"].get(d.stage,0)+1
                stats["total_value"] += d.value or 0
                stats["total_cost"] += d.cost_usd or 0
            stats["total"] = len(deals)
            stats["total_cost_brl"] = round(stats["total_cost"]*5.5,2)
            pending = (await db.execute(select(PendingAction).where(PendingAction.status=="pending").order_by(PendingAction.created_at.desc()).limit(20))).scalars().all()
            # enrich agent
            for d in deals:
                if d.agent_id:
                    d.agent = next((a for a in agents if a.id==d.agent_id), None)
        return await _render("crm.html", request, title="CRM IA", crm_enabled=crm_enabled, deals=deals, stats=stats, pending=pending, agents=agents, q=q, agent_id=agent_id)

@router.post("/crm/enable")
async def crm_enable(request: Request):
    org_id = await _org_filter(request)
    async with db_session() as db:
        from aios.db.models import Organization
        org = await db.get(Organization, org_id)
        if org:
            data = dict(org.extra_data or {})
            data["crm_enabled"] = True
            org.extra_data = data
            await db.commit()
    return RedirectResponse("/dashboard/crm", status_code=303)

@router.post("/crm/create")
async def crm_create(request: Request, lead_name: str = Form(...), lead_email: str = Form(""), lead_phone: str = Form(""), value: float = Form(0), agent_id: str = Form("")):
    org_id = await _org_filter(request)
    from aios.db.models import CrmDeal
    async with db_session() as db:
        d = CrmDeal(org_id=org_id, lead_name=lead_name, lead_email=lead_email, lead_phone=lead_phone, value=value, stage="prospection", agent_id=agent_id or None, extra_data={})
        db.add(d)
        await db.commit()
    return RedirectResponse("/dashboard/crm", status_code=303)

@router.post("/crm/{deal_id}/move")
async def crm_move(request: Request, deal_id: str, stage: str = Form(...)):
    org_id = await _org_filter(request)
    from aios.db.models import CrmDeal
    async with db_session() as db:
        d = await db.get(CrmDeal, deal_id)
        if d and d.org_id==org_id and stage in ["prospection","mql","sql","opportunity","closed_won","closed_lost"]:
            d.stage = stage
            await db.commit()
    return RedirectResponse("/dashboard/crm", status_code=303)

@router.post("/crm/{deal_id}/delete")
async def crm_delete(request: Request, deal_id: str):
    org_id = await _org_filter(request)
    from aios.db.models import CrmDeal
    async with db_session() as db:
        d = await db.get(CrmDeal, deal_id)
        if d and d.org_id==org_id:
            await db.delete(d)
            await db.commit()
    return RedirectResponse("/dashboard/crm", status_code=303)

@router.get("/crm/approve/{pid}")
async def crm_approve(request: Request, pid: str):
    from aios.core.approval import approval_manager
    from aios.api.deps import get_dashboard_user
    u = await get_dashboard_user(request)
    approval_manager.approve(pid, decided_by=u.id if u else "dashboard")
    return RedirectResponse("/dashboard/crm", status_code=303)

@router.get("/crm/reject/{pid}")
async def crm_reject(request: Request, pid: str):
    from aios.core.approval import approval_manager
    from aios.api.deps import get_dashboard_user
    u = await get_dashboard_user(request)
    approval_manager.reject(pid, decided_by=u.id if u else "dashboard")
    return RedirectResponse("/dashboard/crm", status_code=303)

@router.get("/flows", response_class=HTMLResponse)
async def flows_page(request: Request, wf: str = ""):
    return await _render("flow_editor.html", request, title="Flow Editor", wf_id=wf)

@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request):
    org_id = await _org_filter(request)
    from aios.db.models import Memory
    async with db_session() as db:
        mems = (await db.execute(select(Memory).where(Memory.org_id==org_id).order_by(Memory.created_at.desc()).limit(30))).scalars().all()
    return await _render("knowledge.html", request, title="Base Conhecimento", memories=mems)

@router.post("/knowledge/ingest")
async def knowledge_ingest(request: Request):
    org_id = await _org_filter(request)
    form = await request.form()
    file = form.get("file")
    agent_id = form.get("agent_id") or None
    if not file:
        return RedirectResponse("/dashboard/knowledge", status_code=303)
    content = (await file.read()).decode(errors="ignore")[:20000]
    # chunk 800 chars
    chunks = [content[i:i+800] for i in range(0, len(content), 800)][:20]
    from aios.db.models import Memory
    from aios.core.memory import _embed
    async with db_session() as db:
        for ch in chunks:
            try:
                emb = _embed(ch)
            except Exception:
                emb = None
            m = Memory(agent_id=agent_id or (await db.execute(select(Agent).where(Agent.org_id==org_id).limit(1))).scalars().first().id if (await db.execute(select(Agent).where(Agent.org_id==org_id).limit(1))).scalars().first() else (await db.execute(select(Agent).where(Agent.org_id==org_id))).scalars().first().id if False else None, org_id=org_id, type="long_term", content=ch, extra_data={"source": file.filename, "embedding": emb} if emb else {"source": file.filename})
            # fallback agent_id required: use first agent or fake
            if not m.agent_id:
                ag = (await db.execute(select(Agent).where(Agent.org_id==org_id).limit(1))).scalars().first()
                m.agent_id = ag.id if ag else "00000000-0000-0000-0000-000000000000"
            db.add(m)
        await db.commit()
    return RedirectResponse("/dashboard/knowledge", status_code=303)

# ─── Evolution Instances (gerenciar direto no AIOS) ───

@router.get("/evolution", response_class=HTMLResponse)
async def evolution_page(request: Request):
    from aios.core.evolution_api import evo_fetch_instances
    instances = await evo_fetch_instances()
    # map to channels
    org_id = await _org_filter(request)
    async with db_session() as db:
        from aios.db.models import ChannelConnection
        chans = (await db.execute(select(ChannelConnection).where(ChannelConnection.channel_type=="evolution", ChannelConnection.org_id==org_id))).scalars().all()
        chan_map = {c.config.get("instance"): c for c in chans if c.config}
    # enrich instances with channel link
    for inst in instances:
        name = inst.get("name") or inst.get("instanceName") or inst.get("instance", {}).get("instanceName","")
        inst["_name"] = name
        inst["_channel"] = chan_map.get(name)
        inst["_state"] = inst.get("state") or inst.get("instance",{}).get("state","")
    return await _render("evolution.html", request, title="Evolution — Instâncias", instances=instances, chan_map=chan_map)

@router.post("/evolution/create")
async def evolution_create(request: Request, instanceName: str = Form(...), agent_id: str = Form(""), team_id: str = Form("")):
    org_id = await _org_filter(request)
    name = "".join(c for c in instanceName.lower().strip() if c.isalnum() or c in "-_") or "inst01"
    from aios.core.evolution_api import evo_create_instance
    res = await evo_create_instance(name)
    if res.get("ok"):
        # auto-cria canal Evolution vinculado
        from aios.db.models import ChannelConnection
        from aios.config import settings
        async with db_session() as db:
            ch = ChannelConnection(org_id=org_id, label=f"WhatsApp {name}", channel_type="evolution", config={"server_url": settings.evolution_server_url, "api_key": settings.evolution_api_key, "instance": name}, agent_id=agent_id or None, team_id=team_id or None, is_active=True)
            from aios.core.secrets import encrypt_channel_config
            ch.config = encrypt_channel_config(ch.config)
            db.add(ch)
            await db.commit()
    return RedirectResponse("/dashboard/evolution", status_code=303)

@router.get("/evolution/{name}/connect")
async def evolution_connect_page(request: Request, name: str):
    from aios.core.evolution_api import evo_connect, evo_status
    conn = await evo_connect(name)
    st = await evo_status(name)
    from fastapi.responses import JSONResponse
    return JSONResponse({"connect": conn, "status": st})

@router.get("/evolution/{name}/qrcode")
async def evolution_qrcode(request: Request, name: str):
    from aios.core.evolution_api import evo_connect
    data = await evo_connect(name)
    # evolution returns base64 qrcode in data
    from fastapi.responses import JSONResponse
    return JSONResponse(data)

@router.post("/evolution/{name}/logout")
async def evolution_logout(request: Request, name: str):
    from aios.core.evolution_api import evo_logout
    await evo_logout(name)
    return RedirectResponse("/dashboard/evolution", status_code=303)

@router.post("/evolution/{name}/delete")
async def evolution_delete(request: Request, name: str):
    from aios.core.evolution_api import evo_delete
    await evo_delete(name)
    # remove canal
    org_id = await _org_filter(request)
    async with db_session() as db:
        from aios.db.models import ChannelConnection
        chans = (await db.execute(select(ChannelConnection).where(ChannelConnection.channel_type=="evolution"))).scalars().all()
        for c in chans:
            if c.config.get("instance")==name and c.org_id==org_id:
                await db.delete(c)
        await db.commit()
    return RedirectResponse("/dashboard/evolution", status_code=303)

@router.post("/evolution/{name}/restart")
async def evolution_restart(request: Request, name: str):
    from aios.core.evolution_api import evo_restart
    await evo_restart(name)
    return RedirectResponse("/dashboard/evolution", status_code=303)

# ─── Settings (API Keys per org) ───

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    org_id = await _org_filter(request)
    from aios.core.org_settings import ALLOWED_KEYS, mask_key
    async with db_session() as db:
        from aios.db.models import Organization
        org = await db.get(Organization, org_id)
        secrets = {}
        if org and isinstance(org.extra_data, dict):
            secrets = org.extra_data.get("secrets", {}) if isinstance(org.extra_data.get("secrets"), dict) else {}
        masked = {k: mask_key(v) if v else "" for k, v in secrets.items()}
        has_key = {k: bool(secrets.get(k)) for k in ALLOWED_KEYS}
    return await _render("settings.html", request, title="Configurações", secrets=secrets, masked=masked, has_key=has_key)


@router.post("/settings/save")
async def settings_save(request: Request):
    org_id = await _org_filter(request)
    form = await request.form()
    from aios.core.org_settings import ALLOWED_KEYS
    async with db_session() as db:
        from aios.db.models import Organization
        org = await db.get(Organization, org_id)
        if not org:
            return RedirectResponse("/dashboard/settings", status_code=303)
        data = dict(org.extra_data) if isinstance(org.extra_data, dict) else {}
        secrets = dict(data.get("secrets", {})) if isinstance(data.get("secrets"), dict) else {}
        for k in ALLOWED_KEYS:
            val = form.get(k, "")
            if val is not None:
                val = val.strip()
                if val == "" or val.startswith("••••"):
                    continue
                if val:
                    secrets[k] = val
                elif k in secrets:
                    del secrets[k]
            clear_key = f"clear_{k}"
            if form.get(clear_key):
                secrets.pop(k, None)
        data["secrets"] = secrets
        org.extra_data = data
        await db.commit()
    return RedirectResponse("/dashboard/settings?saved=1", status_code=303)


@router.post("/settings/test")
async def settings_test(request: Request):
    from fastapi.responses import JSONResponse
    org_id = await _org_filter(request)
    form = await request.form()
    provider = form.get("provider", "openrouter")
    key_map = {"openrouter": "openrouter_api_key", "openai": "openai_api_key", "anthropic": "anthropic_api_key"}
    skey = key_map.get(provider, "openrouter_api_key")
    test_key = form.get(skey, "").strip()
    if not test_key or test_key.startswith("••••"):
        async with db_session() as db:
            from aios.db.models import Organization
            from aios.core.org_settings import get_org_secret
            org = await db.get(Organization, org_id)
            test_key = get_org_secret(org.extra_data if org else {}, skey) if org else ""
    if not test_key:
        return JSONResponse({"ok": False, "error": "Chave vazia"})
    try:
        import httpx
        if provider == "openrouter":
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {test_key}"})
                ok = r.status_code == 200
                return JSONResponse({"ok": ok, "status": r.status_code, "error": None if ok else r.text[:300]})
        elif provider == "openai":
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {test_key}"})
                ok = r.status_code == 200
                return JSONResponse({"ok": ok, "status": r.status_code, "error": None if ok else r.text[:300]})
        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": test_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, json={"model": "claude-3-haiku-20240307", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]})
                ok = r.status_code in (200, 400)
                if r.status_code == 401:
                    return JSONResponse({"ok": False, "status": 401, "error": "Chave inválida"})
                return JSONResponse({"ok": ok, "status": r.status_code, "error": None if ok else r.text[:300]})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    return JSONResponse({"ok": False, "error": "provider desconhecido"})


# ─── Org Switcher (superadmin only) ───

@router.get("/switch-org/{org_id}")
async def switch_org(request: Request, org_id: str):
    from aios.api.deps import get_dashboard_user
    user = await get_dashboard_user(request)
    if not user or user.role != "superadmin":
        return RedirectResponse("/dashboard", status_code=303)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie(
        key="aios_impersonate_org", value=org_id,
        max_age=86400 * 7, httponly=True, samesite="strict",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        path="/",
    )
    return resp


@router.get("/switch-org/clear")
async def clear_switch(request: Request):
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.delete_cookie("aios_impersonate_org", path="/")
    return resp
