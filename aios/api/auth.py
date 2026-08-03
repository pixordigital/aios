"""Auth routes — register/login with refresh tokens, bcrypt hashing, rate limiting."""

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

logger = logging.getLogger(__name__)

from aios.config import settings
from aios.core.audit import log_audit
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Organization, User
from aios.schemas import LoginRequest, RegisterRequest, TokenResponse


# ─── Email helper (SMTP) ───


async def _send_email(to: str, subject: str, body: str) -> bool:
    """Send email via SMTP. Returns True on success."""
    if not settings.smtp_host:
        logger.warning("SMTP not configured, skipping email to %s", to)
        return False
    try:
        import aiosmtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = settings.smtp_from_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            starttls=True,
        )
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


def _create_email_token(user_id: str, purpose: str, expire_minutes: int = 60) -> str:
    """JWT token for email verification or password reset."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    return jwt.encode(
        {"sub": user_id, "purpose": purpose, "exp": expire, "iat": datetime.now(timezone.utc)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


def _render_email_template(template_name: str, **kwargs) -> str:
    """Load and render an HTML email template."""
    from pathlib import Path
    template_path = Path(__file__).parent.parent / "templates" / "emails" / f"{template_name}.html"
    if not template_path.exists():
        return ""
    html = template_path.read_text()
    for key, value in kwargs.items():
        html = html.replace("{{" + key + "}}", str(value))
    return html

router = APIRouter(prefix="/api/auth", tags=["auth"])

_PASSWORD_MIN = 6
_PASSWORD_MAX = 128

_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_WINDOW_SEC = 300

# ─── Rate limit: Redis with in-memory fallback ───

_login_attempts: dict[str, list[datetime]] = {}  # fallback only
_redis_login = None  # lazy init


async def _get_redis():
    global _redis_login
    if _redis_login is not None:
        return _redis_login
    try:
        import redis.asyncio as aioredis
        _redis_login = aioredis.from_url(settings.redis_url or "redis://localhost:6379", decode_responses=True)
        await _redis_login.ping()
        logger.info("Login rate limiter: Redis")
        return _redis_login
    except Exception:
        _redis_login = None
        logger.warning("Login rate limiter: in-memory fallback (no Redis)")
        return None


async def _rate_limit(key: str):
    now = datetime.now(timezone.utc)
    r = await _get_redis()
    try:
        if r:
            rk = f"rate:login:{key}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(rk, 0, now.timestamp() - _LOGIN_WINDOW_SEC)
            pipe.zadd(rk, {str(now.timestamp()): now.timestamp()})
            pipe.zcard(rk)
            pipe.expire(rk, _LOGIN_WINDOW_SEC)
            results = await pipe.execute()
            count = results[2]
            if count >= _MAX_LOGIN_ATTEMPTS:
                raise HTTPException(429, "Muitas tentativas de login. Tente novamente mais tarde.")
            return
    except HTTPException:
        raise
    except Exception:
        logger.debug("Redis rate limit failed, using in-memory fallback")
    # in-memory fallback
    attempts = _login_attempts.get(key, [])
    attempts = [t for t in attempts if (now - t).total_seconds() < _LOGIN_WINDOW_SEC]
    if len(attempts) >= _MAX_LOGIN_ATTEMPTS:
        raise HTTPException(429, "Muitas tentativas de login. Tente novamente mais tarde.")
    attempts.append(now)
    _login_attempts[key] = attempts


# ─── Password hashing (direct bcrypt with scrypt fallback) ───

try:
    import bcrypt
    def _hash_password(password: str) -> str:
        pwd_bytes = password.encode("utf-8")[:72]
        salt = bcrypt.gensalt(rounds=settings.password_bcrypt_rounds)
        return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

    def _verify_password(password: str, stored: str) -> bool:
        try:
            if stored.startswith("$2a$") or stored.startswith("$2b$") or stored.startswith("$2y$"):
                pwd_bytes = password.encode("utf-8")[:72]
                return bcrypt.checkpw(pwd_bytes, stored.encode("utf-8"))
            if stored.startswith("scrypt$"):
                import hashlib
                _, salt, key_hex = stored.split("$", 2)
                key = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1, dklen=64)
                return secrets.compare_digest(key.hex(), key_hex)
            return False
        except Exception:
            logger.exception("bcrypt verify failed")
            return False
except ImportError:
    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        import hashlib
        key = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
        return f"scrypt${salt}${key.hex()}"

    def _verify_password(password: str, stored: str) -> bool:
        try:
            if not stored.startswith("scrypt$"):
                return False
            import hashlib
            _, salt, key_hex = stored.split("$", 2)
            key = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
            return secrets.compare_digest(key.hex(), key_hex)
        except Exception:
            logger.exception("scrypt verify failed")
            return False


# ─── Input validation ───

_PASSWORD_RE = re.compile(r"^[\x20-\x7E]+$")  # printable ASCII


def _validate_password(password: str):
    if len(password) < _PASSWORD_MIN:
        raise HTTPException(422, f"A senha deve ter pelo menos {_PASSWORD_MIN} caracteres")
    if len(password) > _PASSWORD_MAX:
        raise HTTPException(422, f"A senha deve ter no máximo {_PASSWORD_MAX} caracteres")
    if not _PASSWORD_RE.match(password):
        raise HTTPException(422, "A senha contém caracteres inválidos")
    # check for common patterns
    if password.lower() in ("password", "12345678", "qwerty123", "letmein"):
        raise HTTPException(422, "Senha muito comum")


# ─── JWT helpers ───


def _create_access_token(user_id: str, org_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "org": org_id, "iat": datetime.now(timezone.utc), "exp": expire, "type": "access"},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


def _create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    return jwt.encode(
        {"sub": user_id, "iat": datetime.now(timezone.utc), "exp": expire, "type": "refresh"},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


# ─── Routes ───


@router.post("/register", response_model=TokenResponse)
async def register(request: Request, body: RegisterRequest, db: DatabaseBackend = Depends(get_db_backend)):
    _validate_password(body.password)

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "E-mail já registrado")

    org = Organization(name=body.org_name, slug=body.org_name.lower().replace(" ", "-"))
    db.add(org)
    await db.flush()

    user = User(
        email=body.email.lower().strip(),
        hashed_password=_hash_password(body.password),
        org_id=org.id,
        role="admin",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await log_audit(db, org.id, "user.register", "user", user_id=user.id, details={"email": user.email})

    # send verification email
    vt = _create_email_token(user.id, "email_verify", expire_minutes=1440)
    verify_url = f"{settings.app_url}/api/auth/verify-email?token={vt}"
    html_body = _render_email_template("verification", name=body.org_name, verify_url=verify_url, app_url=settings.app_url)
    await _send_email(user.email, "Verifique seu e-mail — AIOS", html_body or f"Bem-vindo! Verifique seu e-mail: {verify_url}\n\nO link expira em 24h.")

    token = _create_access_token(user.id, org.id)
    refresh = _create_refresh_token(user.id)
    return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=org.id)


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, body: LoginRequest, db: DatabaseBackend = Depends(get_db_backend)):
    await _rate_limit(body.email.lower())

    result = await db.execute(select(User).where(User.email == body.email.lower().strip()))
    user = result.scalar_one_or_none()
    if not user or not _verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "E-mail ou senha inválidos")

    token = _create_access_token(user.id, user.org_id)
    refresh = _create_refresh_token(user.id)
    return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=user.org_id)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request, body: dict, db: DatabaseBackend = Depends(get_db_backend)):
    """Exchange a refresh token for a new access token + new refresh token."""
    raw = body.get("refresh_token", "")
    if not raw:
        raise HTTPException(422, "refresh_token é obrigatório")

    try:
        payload = jwt.decode(raw, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(401, "Token de atualização inválido ou expirado")

    if payload.get("type") != "refresh":
        raise HTTPException(401, "Tipo de token inválido")

    user_id = payload["sub"]
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Usuário não encontrado")

    token = _create_access_token(user.id, user.org_id)
    refresh = _create_refresh_token(user.id)
    return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=user.org_id)


@router.post("/verify-email")
async def verify_email(token: str = Query(...), db: DatabaseBackend = Depends(get_db_backend)):
    """Verify email address using signed token."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(400, "Token de verificação inválido ou expirado")
    if payload.get("purpose") != "email_verify":
        raise HTTPException(400, "Finalidade do token inválida")

    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    if user.email_verified:
        return {"message": "E-mail já verificado"}

    user.email_verified = True
    await db.commit()
    return {"message": "E-mail verificado com sucesso"}


@router.post("/forgot-password")
async def forgot_password(email: str = Query(...), db: DatabaseBackend = Depends(get_db_backend)):
    """Send password reset email."""
    result = await db.execute(select(User).where(User.email == email.lower().strip()))
    user = result.scalar_one_or_none()
    if not user:
        # Don't reveal whether email exists
        return {"message": "Se o e-mail existir, um link de redefinição foi enviado"}

    token = _create_email_token(user.id, "password_reset", expire_minutes=60)
    reset_url = f"{settings.app_url}/auth/reset-password?token={token}"
    html_body = _render_email_template("reset_password", name=user.email.split("@")[0], reset_url=reset_url, app_url=settings.app_url)
    await _send_email(user.email, "Redefinição de senha — AIOS", html_body or f"Redefina sua senha: {reset_url}\n\nO link expira em 1 hora.")
    return {"message": "Se o e-mail existir, um link de redefinição foi enviado"}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: DatabaseBackend = Depends(get_db_backend)):
    """Reset password using signed token."""
    try:
        payload = jwt.decode(body.token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(400, "Token de redefinição inválido ou expirado")
    if payload.get("purpose") != "password_reset":
        raise HTTPException(400, "Finalidade do token inválida")

    _validate_password(body.new_password)
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(404, "Usuário não encontrado")

    user.hashed_password = _hash_password(body.new_password)
    await db.commit()
    return {"message": "Senha redefinida com sucesso"}


# ─── OAuth ───


_oauth_states: dict[str, dict] = {}  # state -> {"provider": str, "org_id": str | None}


async def _oauth_redirect(provider: str, authorize_url: str, client_id: str, scope: str) -> dict:
    """Build OAuth authorize redirect with state."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"provider": provider, "org_id": None}
    params = f"?client_id={client_id}&redirect_uri={settings.app_url}/api/auth/{provider}/callback&response_type=code&scope={scope}&state={state}"
    return {"authorization_url": authorize_url + params}


async def _oauth_exchange(provider: str, code: str, token_url: str, client_id: str, client_secret: str) -> str:
    """Exchange authorization code for access token. Returns access token."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": f"{settings.app_url}/api/auth/{provider}/callback",
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        data = resp.json()
        if "access_token" not in data:
            raise HTTPException(400, f"Falha na troca do token OAuth: {data.get('error_description', data.get('error', 'desconhecido'))}")
        return data["access_token"]


@router.get("/google/login")
async def google_login():
    """Redirect to Google OAuth."""
    if not settings.google_client_id:
        return {"error": "Google OAuth não configurado"}
    return await _oauth_redirect(
        "google",
        "https://accounts.google.com/o/oauth2/v2/auth",
        settings.google_client_id,
        "openid email profile",
    )


@router.get("/google/callback")
async def google_callback(code: str, state: str, db: DatabaseBackend = Depends(get_db_backend)):
    """Handle Google OAuth callback."""
    stored = _oauth_states.pop(state, None)
    if not stored or stored["provider"] != "google":
        raise HTTPException(400, "Parâmetro de estado inválido")

    token = await _oauth_exchange("google", code,
                                   "https://oauth2.googleapis.com/token",
                                   settings.google_client_id, settings.google_client_secret)

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
    provider_user_id = data.get("id")
    email = data.get("email", "").lower().strip()
    name = data.get("name", email)

    if not provider_user_id or not email:
        raise HTTPException(400, "Falha ao obter informações do usuário do Google")

    return await _oauth_login_or_register(db, "google", provider_user_id, email, name)


@router.get("/github/login")
async def github_login():
    """Redirect to GitHub OAuth."""
    if not settings.github_client_id:
        return {"error": "GitHub OAuth não configurado"}
    return await _oauth_redirect(
        "github",
        "https://github.com/login/oauth/authorize",
        settings.github_client_id,
        "read:user user:email",
    )


@router.get("/github/callback")
async def github_callback(code: str, state: str, db: DatabaseBackend = Depends(get_db_backend)):
    """Handle GitHub OAuth callback."""
    stored = _oauth_states.pop(state, None)
    if not stored or stored["provider"] != "github":
        raise HTTPException(400, "Parâmetro de estado inválido")

    token = await _oauth_exchange("github", code,
                                   "https://github.com/login/oauth/access_token",
                                   settings.github_client_id, settings.github_client_secret)

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        data = resp.json()
    provider_user_id = str(data.get("id"))
    email = data.get("email", "")

    # GitHub may not return email in user scope — fetch emails separately
    if not email:
        async with httpx.AsyncClient() as client:
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            for e in emails_resp.json():
                if e.get("primary") and e.get("verified"):
                    email = e["email"]
                    break

    if not provider_user_id or not email:
        raise HTTPException(400, "Falha ao obter informações do usuário do GitHub")


    return await _oauth_login_or_register(db, "github", provider_user_id, email.lower().strip(), data.get("login", email))


async def _oauth_login_or_register(db: DatabaseBackend, provider: str, provider_user_id: str, email: str, name: str) -> TokenResponse:
    """Find existing OAuth account or create user + OAuth account."""
    from aios.db.models import OAuthAccount

    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    oa = result.scalar_one_or_none()

    if oa:
        user = await db.get(User, oa.user_id)
        if user:
            token = _create_access_token(user.id, user.org_id)
            refresh = _create_refresh_token(user.id)
            return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=user.org_id)

    # Check if user exists by email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        # Create new org + user
        org = Organization(name=name, slug=email.split("@")[0])
        db.add(org)
        await db.flush()
        user = User(
            email=email,
            hashed_password="",  # OAuth users have no password
            org_id=org.id,
            role="admin",
            email_verified=True,
        )
        db.add(user)
        await db.flush()
        await log_audit(db, org.id, "user.register_oauth", "user", user_id=user.id,
                        details={"provider": provider, "email": email})

    oa = OAuthAccount(user_id=user.id, provider=provider, provider_user_id=provider_user_id)
    db.add(oa)
    await db.commit()

    token = _create_access_token(user.id, user.org_id)
    refresh = _create_refresh_token(user.id)
    return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=user.org_id)
