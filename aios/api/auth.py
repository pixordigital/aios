"""Auth routes — register/login with rate limit stubs and input validation."""

import hashlib
import re
import secrets
from datetime import datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.config import settings
from aios.db.engine import get_db
from aios.db.models import Organization, User
from aios.schemas import LoginRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

_PASSWORD_MIN = 8
_PASSWORD_MAX = 128

# ponytail: in-memory rate limit counters. Redis-backed in multi-worker prod.
_login_attempts: dict[str, list[datetime]] = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_WINDOW_SEC = 300


def _rate_limit(key: str):
    now = datetime.utcnow()
    attempts = _login_attempts.get(key, [])
    attempts = [t for t in attempts if (now - t).total_seconds() < _LOGIN_WINDOW_SEC]
    if len(attempts) >= _MAX_LOGIN_ATTEMPTS:
        raise HTTPException(429, "Too many login attempts. Try again later.")
    attempts.append(now)
    _login_attempts[key] = attempts


def _hash_password(password: str) -> str:
    """scrypt hash with random salt. Output format: hex(salt)$hex(key)."""
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return f"{salt}${key.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, key_hex = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False  # malformed hash
    key = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return secrets.compare_digest(key.hex(), key_hex)


def _validate_password(password: str):
    if len(password) < _PASSWORD_MIN:
        raise HTTPException(400, f"Password must be at least {_PASSWORD_MIN} characters")
    if len(password) > _PASSWORD_MAX:
        raise HTTPException(400, f"Password must be at most {_PASSWORD_MAX} characters")
    if not re.search(r"[A-Za-z]", password):
        raise HTTPException(400, "Password must contain at least one letter")
    if not re.search(r"[0-9]", password):
        raise HTTPException(400, "Password must contain at least one number")


def create_jwt(user_id: str, org_id: str) -> str:
    payload = {
        "sub": user_id,
        "org": org_id,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    _validate_password(body.password)

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email already registered")

    org = Organization(name=body.org_name, slug=body.org_name.lower().replace(" ", "-"))
    db.add(org)
    await db.flush()

    user = User(
        email=body.email.lower().strip(),
        hashed_password=_hash_password(body.password),
        org_id=org.id,
    )
    db.add(user)
    await db.commit()

    token = create_jwt(user.id, org.id)
    return TokenResponse(access_token=token, user_id=user.id, org_id=org.id)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    _rate_limit(body.email.lower())

    result = await db.execute(select(User).where(User.email == body.email.lower().strip()))
    user = result.scalar_one_or_none()
    if not user or not _verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")

    token = create_jwt(user.id, user.org_id)
    return TokenResponse(access_token=token, user_id=user.id, org_id=user.org_id)
