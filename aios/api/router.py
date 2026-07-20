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

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(agents_router)
api_router.include_router(teams_router)
api_router.include_router(conversations_router)
api_router.include_router(channels_router)
api_router.include_router(tools_router)
api_router.include_router(analytics_router)
api_router.include_router(billing_router)
api_router.include_router(files_router)
api_router.include_router(admin_api_router)
