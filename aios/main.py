import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aios.api.router import api_router
from aios.config import settings
from aios.core.storage import ensure_storage
from aios.db.engine import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REQUEST_COUNT = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AIOS...")
    await init_db()
    await ensure_storage()
    logger.info("Database initialized")

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
        org = (await sess.execute(select(Organization).where(Organization.slug == "default"))).scalar_one_or_none()
        if org is None:
            org = Organization(name="Default", slug="default")
            sess.add(org)
            await sess.commit()
            logger.info("Seeded default organization: %s", org.id)

        await sess.commit()
    logger.info("Cleared stale AgentInstance statuses")

    # channel lifecycle — background workers
    _channel_tasks: list = []

    if settings.dashboard_enabled:
        from aios.dashboard.app import router as dash_router
        app.include_router(dash_router)
        logger.info("Dashboard mounted at /dashboard")

    # WhatsApp webhook route
    from aios.api.whatsapp_webhook import router as wa_router
    app.include_router(wa_router)
    logger.info("WhatsApp webhook mounted")

    # start active channel background workers
    from aios.db.models import ChannelConnection
    from aios.channels.manager import manager as channel_mgr
    async with async_session() as sess:
        active = (await sess.execute(
            select(ChannelConnection).where(ChannelConnection.is_active == True)
        )).scalars().all()
        for conn in active:
            try:
                # load assigned agent or team
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
            pass
    logger.info("Shutting down AIOS...")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# ponytail: restrict origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# dashboard auth middleware
AUTH_EXEMPT = {"/dashboard/login", "/dashboard/register", "/dashboard/logout", "/dashboard/"}  # trailing slash variant


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
        # impersonation override for superadmins
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
    """Reject requests with body > 10MB."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:
        return JSONResponse(status_code=413, content={"error": "Request too large"})
    response = await call_next(request)
    return response


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    response = await call_next(request)
    response.headers["X-Request-ID"] = str(REQUEST_COUNT)
    return response


app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "requests": REQUEST_COUNT}


@app.exception_handler(Exception)
async def global_exception(request: Request, exc: Exception):
    logger.error("Unhandled error: %s | path=%s", exc, request.url.path, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


def run():
    import uvicorn
    uvicorn.run("aios.main:app", host="0.0.0.0", port=8777, reload=True)
