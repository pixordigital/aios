from fastapi import APIRouter

from .agents import router as agents_router
from .analytics import router as analytics_router
from .auth import router as auth_router
from .channels import router as channels_router
from .conversations import router as conversations_router
from .teams import router as teams_router
from .tools import router as tools_router
from .billing import router as billing_router
from .files import router as files_router
from .admin_api import router as admin_api_router
from .ws import router as ws_router
from .approvals import router as approvals_router
from .skills import router as skills_router
from .library import router as library_router
from .rubrics import router as rubrics_router
from .threads import router as threads_router
from .meta import router as meta_router
from .workflows import router as workflows_router
from .versions import router as versions_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(agents_router)
api_router.include_router(versions_router)
api_router.include_router(teams_router)
api_router.include_router(workflows_router)
api_router.include_router(conversations_router)
api_router.include_router(channels_router)
api_router.include_router(tools_router)
api_router.include_router(analytics_router)
api_router.include_router(billing_router)
api_router.include_router(files_router)
api_router.include_router(admin_api_router)
api_router.include_router(ws_router)
api_router.include_router(approvals_router)
api_router.include_router(skills_router)
api_router.include_router(library_router)
api_router.include_router(rubrics_router)
api_router.include_router(threads_router)
api_router.include_router(meta_router)
