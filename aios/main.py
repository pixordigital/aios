"""AIOS — main FastAPI application."""

import asyncio
import logging
from contextlib import asynccontextmanager

from aios.core.log_config import setup_logging
setup_logging()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aios.api.router import api_router
from aios.config import settings
from aios.core.storage import ensure_storage
from aios.core.syscalls import dispatcher as syscall_dispatcher
from aios.core.scheduler import scheduler
from aios.core.context_manager import context_manager
from aios.db.backend import init_backends, registry
from aios.db.engine import init_db

logger = logging.getLogger(__name__)

import threading
REQUEST_COUNT = 0
_request_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AIOS...")

    # Validate config for production
    _validate_db_config()
    _validate_security_config()

    await init_backends()
    await init_db()
    await ensure_storage()

    # Sentry — only if DSN configured
    if settings.sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment="production" if not settings.debug else "development",
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("Sentry initialized (DSN configured)")

    # Mount unified error handlers
    from aios.api.errors import register_error_handlers
    register_error_handlers(app)
    logger.info("Error handlers registered")

    
    # Register syscall handlers
    await _register_syscall_handlers()
    logger.info("Syscall handlers registered")

    # Start event bus (processes inbound messages from channels)
    from aios.core.event_bus import event_bus
    await event_bus.start()
    logger.info("Event bus started")

    # Log scheduler stats periodically
    async def _log_scheduler():
        while True:
            await asyncio.sleep(300)
            summary = scheduler.summary()
            logger.info("Scheduler: %d queued, %d running, %d total processes",
                        summary["queued"], summary["running"], summary["total_processes"])
    asyncio.create_task(_log_scheduler())

    # Periodic DB failover check
    async def _failover_watch():
        while True:
            await asyncio.sleep(15)
            try:
                changed = await registry.check_failover()
                if changed:
                    logger.info("Backend failover state changed: %s", registry.summary())
            except Exception:
                logger.exception("Failover check failed")
    asyncio.create_task(_failover_watch())

    # clear stale "running" instances — they don't survive restart
    from sqlalchemy import update as sql_update
    from aios.db.models import AgentInstance, Organization
    from aios.db.engine import async_session
    async with async_session() as sess:
        await sess.execute(
            sql_update(AgentInstance)
            .where(AgentInstance.status == "running")
            .values(status="stopped")
        )

        # seed default org for dashboard (bypasses auth)
        from sqlalchemy import select
        try:
            org = (await sess.execute(select(Organization).where(Organization.slug == "default"))).scalar_one_or_none()
            if org is None:
                org = Organization(name="Default", slug="default")
                sess.add(org)
                await sess.commit()
                logger.info("Seeded default organization: %s", org.id)
        except Exception:
            logger.debug("Default org already exists (concurrent seed)")

        await sess.commit()
    logger.info("Cleared stale AgentInstance statuses")

    # channel lifecycle — background workers
    _channel_tasks: list = []

    if settings.dashboard_enabled:
        from aios.dashboard.app import router as dash_router
        app.include_router(dash_router)
        logger.info("Dashboard mounted at /dashboard")

    # WhatsApp webhook routes
    from aios.api.whatsapp_webhook import router as wa_router
    app.include_router(wa_router)
    from aios.api.evolution_webhook import router as evo_router
    app.include_router(evo_router)
    logger.info("WhatsApp + Evolution webhooks mounted")

    # start active channel background workers
    from aios.db.models import ChannelConnection
    from aios.channels.manager import manager as channel_mgr
    async with async_session() as sess:
        active = (await sess.execute(
            select(ChannelConnection).where(ChannelConnection.is_active == True)
        )).scalars().all()
        for conn in active:
            try:
                agent_or_team = None
                if conn.agent_id:
                    from aios.db.models import Agent
                    agent_or_team = await sess.get(Agent, conn.agent_id)
                elif conn.team_id:
                    from aios.db.models import Team
                    from sqlalchemy.orm import selectinload
                    agent_or_team = await sess.get(Team, conn.team_id, options=[selectinload(Team.agents)])

                ch = channel_mgr.build(conn, agent_or_team, sess)
                await channel_mgr.start(ch)
                _channel_tasks.append(ch)
                logger.info("Channel %s (%s) started", conn.label, conn.channel_type)
            except Exception:
                logger.exception("Failed to start channel %s", conn.label)

    yield

    for ch in _channel_tasks:
        try:
            await ch.stop()
        except Exception:
            logger.exception("Channel stop failed")

    # close Redis pool
    from aios.tasks.queue import close_pool
    try:
        await close_pool()
    except Exception:
        pass

    # Stop event bus
    from aios.core.event_bus import event_bus
    await event_bus.stop()

    logger.info("Shutting down AIOS...")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AIOS — multi-tenant AI agent orchestration platform with billing, channels, and observability.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Rate limiter middleware (must be added at app creation, not in lifespan)
if not settings.debug:
    from aios.api.ratelimit import limiter
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(status_code=429, content={"type": "about:blank", "title": "Rate limit exceeded", "status": 429, "detail": "Try again later.", "instance": str(request.url.path)})

app.include_router(api_router)


# CSP middleware
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if not settings.debug:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
    return response

# CORS — locked to configured origins in production
_cors_origins = ["*"]
if settings.cors_origins:
    _cors_origins = [o.strip() for o in settings.cors_origins.split(",")]
elif not settings.debug:
    _cors_origins = [settings.app_url.rstrip("/")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# dashboard auth middleware
AUTH_EXEMPT = {"/dashboard/login", "/dashboard/register", "/dashboard/logout", "/dashboard/"}

# ponytail: referer check for dashboard POST — CSRF defense without token state
_DASHBOARD_REFERER_OK = True  # CSRF referer check enabled


@app.middleware("http")
async def dashboard_csrf(request: Request, call_next):
    """Reject dashboard POST from external origins."""
    if request.method == "POST" and request.url.path.startswith("/dashboard"):
        referer = request.headers.get("referer", "")
        if not referer.startswith(str(request.base_url)):
            if _DASHBOARD_REFERER_OK:
                return JSONResponse(status_code=403, content={"error": "CSRF: invalid origin"})
    return await call_next(request)


@app.middleware("http")
async def dashboard_auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/dashboard") and path not in AUTH_EXEMPT:
        from aios.api.deps import get_dashboard_user
        user = await get_dashboard_user(request)
        if not user:
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/dashboard/login", status_code=303)
        request.state.user_id = user.id
        request.state.user_email = user.email
        request.state.is_superadmin = user.role == "superadmin"
        imp_org = request.cookies.get("aios_impersonate_org")
        if user.role == "superadmin" and imp_org:
            request.state.org_id = imp_org
            request.state.is_impersonating = True
        else:
            request.state.org_id = user.org_id
            request.state.is_impersonating = False
    return await call_next(request)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:
        return JSONResponse(status_code=413, content={"error": "Request too large"})
    response = await call_next(request)
    return response


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    global REQUEST_COUNT
    with _request_lock:
        REQUEST_COUNT += 1
        req_id = REQUEST_COUNT
    response = await call_next(request)
    response.headers["X-Request-ID"] = str(req_id)
    return response


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    from aios.core.tracing import new_trace_id
    tid = new_trace_id()
    response = await call_next(request)
    response.headers["X-Trace-ID"] = tid
    return response


# ─── Scheduler status endpoint ───


@app.get("/system/scheduler")
async def scheduler_status():
    return scheduler.summary()


@app.get("/system/context")
async def context_status():
    return context_manager.stats()


# ─── Syscall handlers ───

def _validate_db_config():
    """Warn or refuse on production-unready DB configurations."""
    from aios.db.engine import _is_sqlite
    if _is_sqlite():
        if settings.debug:
            logger.warning("SQLite in use — not recommended for production. Set AIOS_DATABASE_URL to PostgreSQL.")
        else:
            raise RuntimeError(
                "Refusing to start: SQLite is not supported in production mode. "
                "Set AIOS_DATABASE_URL to a PostgreSQL connection string "
                "(e.g. postgresql+asyncpg://...). Supabase connection strings work directly."
            )


def _validate_security_config():
    """Refuse startup if JWT secret is the default or empty."""
    if not settings.jwt_secret or settings.jwt_secret == "":
        raise RuntimeError(
            "AIOS_JWT_SECRET is not set. Generate a secure random string and set it "
            "in your environment (e.g. openssl rand -hex 32)."
        )
    if settings.jwt_secret == "change-me-in-production":
        raise RuntimeError(
            "AIOS_JWT_SECRET is still the default value 'change-me-in-production'. "
            "Generate a new secret with: openssl rand -hex 32"
        )
    if not settings.https_only and not settings.debug:
        logger.warning("HTTPS is not enforced. Set AIOS_HTTPS_ONLY=true in production.")


async def _register_syscall_handlers():
    """Register handlers for each syscall type."""
    from aios.core.syscalls import SyscallType
    from aios.core.providers import get_provider
    from aios.core.storage import save_artifact, get_artifact_content, list_artifacts
    from aios.db.backend import db_session

    async def handle_llm_chat(req, **extra):
        params = req.params
        llm = get_provider(params.get("model", "openai/gpt-4o"))
        return await llm.chat_retry(
            messages=params["messages"],
            model=params.get("model", "openai/gpt-4o"),
            temperature=params.get("temperature", 0.7),
            max_tokens=params.get("max_tokens", 4096),
            tools=params.get("tools"),
            tool_choice=params.get("tool_choice"),
        )

    async def handle_llm_chat_stream(req, **extra):
        params = req.params
        llm = get_provider(params.get("model", "openai/gpt-4o"))
        return llm.chat_stream_retry(
            messages=params["messages"],
            model=params.get("model", "openai/gpt-4o"),
            temperature=params.get("temperature", 0.7),
            max_tokens=params.get("max_tokens", 4096),
            tools=params.get("tools"),
        )

    async def handle_memory_read(req, **extra):
        """Read recent memory for a conversation."""
        # In-memory reads are handled directly by MemoryManager
        return {"ok": True, "note": "memory reads route through MemoryManager"}

    async def handle_memory_write(req, **extra):
        return {"ok": True, "note": "memory writes route through MemoryManager"}

    async def handle_storage_save(req, **extra):
        params = req.params
        async with db_session() as db:
            result = await save_artifact(
                db=db,
                org_id=params.get("org_id", ""),
                filename=params.get("filename", "file"),
                content=params.get("content", b""),
                content_type=params.get("content_type", "application/octet-stream"),
                conversation_id=params.get("conversation_id"),
                agent_id=req.agent_id,
                description=params.get("description", ""),
            )
            return result

    async def handle_storage_read(req, **extra):
        params = req.params
        async with db_session() as db:
            return await get_artifact_content(params["artifact_id"], db)

    async def handle_storage_list(req, **extra):
        params = req.params
        async with db_session() as db:
            return await list_artifacts(
                db=db,
                org_id=params.get("org_id", ""),
                conversation_id=params.get("conversation_id"),
            )

    syscall_dispatcher.register(SyscallType.LLM_CHAT, handle_llm_chat)
    syscall_dispatcher.register(SyscallType.LLM_CHAT_STREAM, handle_llm_chat_stream)
    syscall_dispatcher.register(SyscallType.MEMORY_READ, handle_memory_read)
    syscall_dispatcher.register(SyscallType.MEMORY_WRITE, handle_memory_write)
    syscall_dispatcher.register(SyscallType.STORAGE_SAVE, handle_storage_save)
    syscall_dispatcher.register(SyscallType.STORAGE_READ, handle_storage_read)
    syscall_dispatcher.register(SyscallType.STORAGE_LIST, handle_storage_list)


@app.get("/health/live")
async def health_live():
    """Lightweight liveness — process is alive and responding."""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/health/ready")
async def health_ready():
    """Readiness — database and other dependencies are reachable."""
    issues = {}
    # check DB
    try:
        db_ok = await registry.active.health() if registry.active else False
        if not db_ok:
            issues["database"] = "unreachable"
    except Exception as e:
        logger.exception("Health check database error")
        issues["database"] = str(e)

    if issues:
        return {"status": "degraded", "issues": issues}, 503
    return {"status": "ok"}


@app.get("/health")
async def health():
    db_status = "unknown"
    try:
        db_status = "ok" if await registry.active.health() else "down"
    except Exception:
        logger.exception("Health endpoint DB check failed")
        db_status = "error"
    return {
        "status": "ok",
        "version": "0.1.0",
        "requests": REQUEST_COUNT,
        "db": db_status,
        "backend": registry.summary(),
        "scheduler": scheduler.summary(),
        "context": context_manager.stats(),
    }


def run():
    import uvicorn
    uvicorn.run("aios.main:app", host="0.0.0.0", port=8777, reload=True)
