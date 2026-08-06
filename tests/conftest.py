"""Test configuration and fixtures."""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aios.config import settings


# Shared file-backed SQLite for tests. Set BEFORE importing engine/main: those
# modules build their engine/limiter from settings at import time, and .env points
# at docker-network services (supabase-db, redis) unreachable in CI/sandbox.
# File (not :memory:) so the global engine used by dashboard db_session() paths
# and the per-test session see the same data.
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test.db")
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
settings.jwt_secret = "test-secret"
settings.debug = True
settings.database_url = TEST_DATABASE_URL
settings.redis_url = ""
settings.storage_backend = "local"
settings.admin_master_key = "test-admin-key"

from aios.db.engine import Base, async_session, get_db, engine
from aios.db.models import Organization, User
from aios.main import app


@pytest_asyncio.fixture(loop_scope="function", autouse=True)
async def _fresh_db():
    """Reset the shared test DB before each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(loop_scope="function")
async def test_engine():
    """Global engine — same DB as dashboard db_session() paths."""
    yield engine
    # no dispose: module-level engine owned by app


@pytest_asyncio.fixture(loop_scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session on the shared engine."""
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture(loop_scope="function")
async def test_db_session(test_session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """Override get_db and get_db_backend dependencies for tests."""
    from aios.db.backend import get_db_backend, registry
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend

    test_backend = SQLAlchemyBackend(test_session)
    registry.init(test_backend, None)

    async def _get_db():
        yield test_session

    async def _get_db_backend():
        yield test_backend

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_db_backend] = _get_db_backend
    # Auth overrides removed; using real authentication flow
    yield test_session
    app.dependency_overrides.clear()



@pytest_asyncio.fixture(loop_scope="function")
async def test_org(test_session: AsyncSession) -> Organization:
    """Create test organization."""
    org = Organization(
        name="Test Org",
        slug="test-org",
        extra_data={"plan": "pro"}
    )
    test_session.add(org)
    await test_session.commit()
    await test_session.refresh(org)
    return org


@pytest_asyncio.fixture(loop_scope="function")
async def test_user(test_session: AsyncSession, test_org: Organization) -> User:
    """Create test user."""
    from aios.api.auth import _hash_password
    user = User(
        email="test@example.com",
        hashed_password=_hash_password("testpass123"),
        org_id=test_org.id,
        role="admin"
    )
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)
    return user


@pytest_asyncio.fixture(loop_scope="function")
async def auth_headers(test_user: User) -> dict[str, str]:
    """Generate auth headers for test user."""
    import jwt
    from datetime import datetime, timedelta, timezone

    token = jwt.encode(
        {
            "sub": test_user.id,
            "org": test_user.org_id,
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=60)
        },
        "test-secret",  # matches test JWT secret
        algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(loop_scope="function")
async def async_client(test_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(loop_scope="function")
async def auth_client(async_client: AsyncClient, auth_headers: dict) -> AsyncClient:
    """Async client with auth headers."""
    async_client.headers.update(auth_headers)
    return async_client