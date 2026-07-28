"""Test configuration and fixtures."""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aios.config import settings
from aios.db.engine import Base, get_db
from aios.db.models import Organization, User
from aios.main import app


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
settings.jwt_secret = "test-secret"
settings.debug = True


@pytest_asyncio.fixture(loop_scope="function")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
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