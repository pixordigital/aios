"""Auth routes — register/login with refresh tokens, bcrypt hashing, rate limiting.
Supports Ed25519 JWT signing with HS256 fallback for backward compatibility during rotation.
"""

import base64
import logging
import re
import secrets
import uuid
import time
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

logger = logging.getLogger(__name__)

from aios.config import settings
from aios.core.audit import log_audit
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Organization, User
from aios.schemas import LoginRequest, RegisterRequest, TokenResponse


# ─── JWT Key Management (Ed25519 with HS256 fallback) ───

_JWT_PRIVATE_KEY: ed25519.Ed25519PrivateKey | None = None
_JWT_PUBLIC_KEY: ed25519.Ed25519PublicKey | None = None
_JWT_KEY_ID: str = ""


def _load_ed25519_keys() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey, str]:
    """Load or generate Ed25519 key pair for JWT signing."""
    global _JWT_PRIVATE_KEY, _JWT_PUBLIC_KEY, _JWT_KEY_ID
    
    if _JWT_PRIVATE_KEY is not None and _JWT_PUBLIC_KEY is not None:
        return _JWT_PRIVATE_KEY, _JWT_PUBLIC_KEY, _JWT_KEY_ID
    
    # Try to load from settings
    if settings.jwt_ed25519_private_key and settings.jwt_ed25519_public_key:
        try:
            private_key_b64 = settings.jwt_ed25519_private_key
            public_key_b64 = settings.jwt_ed25519_public_key
            
            _JWT_PRIVATE_KEY = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
            _JWT_PUBLIC_KEY = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
            _JWT_KEY_ID = "ed25519-v1"
            logger.info("Loaded Ed25519 JWT keys from config")
            return _JWT_PRIVATE_KEY, _JWT_PUBLIC_KEY, _JWT_KEY_ID
        except Exception as e:
            # Configured but unloadable. Minting an ephemeral pair here would
            # silently invalidate every outstanding session AND change the key
            # id, so verification of old tokens fails in a confusing way.
            # Refuse instead; the operator fixes the config and restarts.
            raise RuntimeError(f"Ed25519 JWT keys are configured but unloadable: {e}") from e
    
    # Generate new key pair if not configured
    _JWT_PRIVATE_KEY = ed25519.Ed25519PrivateKey.generate()
    _JWT_PUBLIC_KEY = _JWT_PRIVATE_KEY.public_key()
    _JWT_KEY_ID = f"ed25519-gen-{secrets.token_hex(4)}"
    logger.warning("Generated ephemeral Ed25519 JWT keys — set AIOS_JWT_ED25519_PRIVATE_KEY and AIOS_JWT_ED25519_PUBLIC_KEY for persistence")
    assert _JWT_PRIVATE_KEY is not None and _JWT_PUBLIC_KEY is not None
    return _JWT_PRIVATE_KEY, _JWT_PUBLIC_KEY, _JWT_KEY_ID


def _get_jwt_signing_key() -> tuple[bytes | ed25519.Ed25519PrivateKey, str, str]:
    """Get the appropriate signing key based on configuration.
    Returns (key, algorithm, key_id).
    """
    # If Ed25519 keys are configured, use them
    if settings.jwt_ed25519_private_key and settings.jwt_ed25519_public_key:
        private_key, _, key_id = _load_ed25519_keys()
        return private_key, "EdDSA", key_id
    
    # Fallback to HS256
    return settings.jwt_secret.encode(), "HS256", "hs256-v1"


def _get_jwt_verification_key(algorithm: str | None = None) -> bytes | ed25519.Ed25519PublicKey:
    """Get the appropriate verification key."""
    if algorithm == "EdDSA" or (algorithm is None and settings.jwt_ed25519_public_key):
        _, public_key, _ = _load_ed25519_keys()
        return public_key
    return settings.jwt_secret.encode()


def _create_jwt_token(payload: dict, token_type: str = "access") -> tuple[str, str]:
    """Create JWT token with appropriate algorithm.
    Returns (token, key_id).
    """
    key, algorithm, key_id = _get_jwt_signing_key()
    payload["type"] = token_type
    payload["kid"] = key_id
    token = jwt.encode(payload, key, algorithm=algorithm)
    return token, key_id


def _decode_jwt_token(token: str) -> dict | None:
    """Decode JWT token trying both EdDSA and HS256."""
    # Try to get key_id from header
    try:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid", "")
        algorithm = header.get("alg", "")
    except Exception:
        key_id = ""
        algorithm = ""
    
    # Determine verification key based on key_id or algorithm
    if key_id.startswith("ed25519") or algorithm == "EdDSA":
        public_key = _get_jwt_verification_key("EdDSA")
        algorithms = ["EdDSA"]
    else:
        public_key = _get_jwt_verification_key("HS256")
        algorithms = ["HS256"]
    
    try:
        return jwt.decode(token, public_key, algorithms=algorithms)
    except jwt.PyJWTError as e:
        # Fallback: try the other algorithm
        if algorithms == ["EdDSA"]:
            public_key = _get_jwt_verification_key("HS256")
            try:
                return jwt.decode(token, public_key, algorithms=["HS256"])
            except jwt.PyJWTError:
                pass
        else:
            _, public_key, _ = _load_ed25519_keys()
            try:
                return jwt.decode(token, public_key, algorithms=["EdDSA"])
            except jwt.PyJWTError:
                pass
        logger.debug("JWT decode failed: %s", e)
        return None


def _create_email_token(user_id: str, purpose: str, expire_minutes: int = 60) -> str:
    """JWT token for email verification or password reset."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    token, _ = _create_jwt_token(
        {"sub": user_id, "purpose": purpose, "exp": expire, "iat": datetime.now(timezone.utc)},
        token_type="email"
    )
    return token


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


def get_jwt_key_info() -> dict:
    """Get current JWT key configuration info for admin/monitoring."""
    private_key, public_key, key_id = _load_ed25519_keys()
    has_ed25519 = bool(settings.jwt_ed25519_private_key and settings.jwt_ed25519_public_key)
    rotation_days = settings.jwt_key_rotation_days or 90
    
    return {
        "algorithm": "EdDSA" if has_ed25519 else "HS256",
        "key_id": key_id,
        "has_persistent_keys": has_ed25519,
        "rotation_days": rotation_days,
        "public_key_fingerprint": base64.b64encode(
            public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
        ).decode()[:16] if public_key else None,
    }


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
            start_tls=True,
        )
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


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


# A real bcrypt hash of a random string, used only to burn the same CPU on a
# failed login for an unknown email as for a wrong password. Regenerated at
# import; its plaintext is discarded and never matches a real credential.
_DUMMY_HASH = _hash_password(secrets.token_urlsafe(32))


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
    token, _ = _create_jwt_token(
        {"sub": user_id, "org": org_id, "iat": datetime.now(timezone.utc), "exp": expire},
        token_type="access"
    )
    return token


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalise a datetime read back from the DB to timezone-aware UTC.

    refresh_tokens.expires_at is a plain DateTime column, so both SQLite and
    Postgres hand it back naive. Comparing that to datetime.now(timezone.utc)
    raised TypeError on every /refresh. Everything is written in UTC, so
    attaching the zone is correct rather than a guess.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _new_jti() -> str:
    return uuid.uuid4().hex


async def _issue_refresh(db, user_id: str) -> str:
    """Mint a refresh token and record its jti so it can be revoked later."""
    from aios.db.models import RefreshToken

    jti = _new_jti()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    token, _ = _create_jwt_token(
        {"sub": user_id, "jti": jti, "iat": datetime.now(timezone.utc), "exp": expire},
        token_type="refresh",
    )
    db.add(RefreshToken(jti=jti, user_id=user_id, expires_at=expire))
    await db.commit()
    return token


def _create_refresh_token(user_id: str) -> str:
    """Unsigned issuance for call sites that have no db handle.

    Every authenticated path uses _issue_refresh; this stays only so nothing
    that imports it breaks, and it deliberately produces a token whose jti was
    never persisted -- /refresh rejects those, which fails closed rather than
    minting an unrevocable credential.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    token, _ = _create_jwt_token(
        {"sub": user_id, "iat": datetime.now(timezone.utc), "exp": expire},
        token_type="refresh",
    )
    return token


async def _revoke_all_for_user(db, user_id: str) -> int:
    """Kill every outstanding refresh token. Used by logout and password reset."""
    from sqlalchemy import update as _update

    from aios.db.models import RefreshToken

    res = await db.execute(
        _update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return int(res.rowcount or 0)


def _verify_jwt_token(token: str) -> dict | None:
    """Verify JWT token using appropriate algorithm."""
    return _decode_jwt_token(token)


# ─── Login allowlist (single-operator lockdown) ───


def _login_allowlist() -> set[str]:
    """Parse AIOS_LOGIN_ALLOWLIST into lowercased emails. Empty = not configured."""
    raw = (settings.login_allowlist or "").replace(";", ",")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _is_login_allowed(email: str) -> bool:
    """True if this address may authenticate. Open to all when unconfigured."""
    allowed = _login_allowlist()
    if not allowed:
        return True
    return (email or "").strip().lower() in allowed


def _is_allowlisted(email: str) -> bool:
    """True only if the allowlist is configured AND contains this address.

    Distinct from _is_login_allowed: used for trust decisions (e.g. skipping
    the email-verification gate), where an unconfigured list must NOT imply
    trust for everyone.
    """
    allowed = _login_allowlist()
    return bool(allowed) and (email or "").strip().lower() in allowed


# ─── Routes ───


@router.post("/register", response_model=TokenResponse)
async def register(request: Request, body: RegisterRequest, db: DatabaseBackend = Depends(get_db_backend)):
    if not settings.registration_enabled:
        raise HTTPException(403, "Cadastros temporariamente fechados — entre em contato")
    # Defense in depth: even if registration is ever flipped back on, only
    # allowlisted addresses may create accounts.
    if not _is_login_allowed(body.email):
        logger.warning("registration rejected for non-allowlisted address")
        raise HTTPException(403, "Cadastros temporariamente fechados — entre em contato")
    _validate_password(body.password)
    # blacklist check (email/domain)
    try:
        email_l = body.email.lower().strip()
        domain = email_l.split("@")[1] if "@" in email_l else ""
        # check control plane blacklist table (if exists)
        # Params are bound into the statement: DatabaseBackend.execute(stmt)
        # takes one argument. Passing a dict positionally raised TypeError,
        # which the surrounding `except Exception` swallowed — so the blacklist
        # silently never blocked anyone.
        from sqlalchemy import text
        hit = await db.execute(
            text("SELECT 1 FROM blacklist WHERE email=:e OR domain=:d LIMIT 1")
            .bindparams(e=email_l, d=domain)
        )
        if hit.first():
            raise HTTPException(403, "Cadastro bloqueado — entre em contato com suporte")
    except HTTPException:
        raise
    except Exception:
        pass

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
    refresh = await _issue_refresh(db, user.id)
    return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=org.id)


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, body: LoginRequest, db: DatabaseBackend = Depends(get_db_backend)):
    # Key on email AND client IP. Keying on email alone meant anyone who knew a
    # customer's address could lock that account out for the whole window, and a
    # distributed attack on one account was never throttled.
    _ip = request.client.host if request and request.client else "unknown"
    await _rate_limit(f"{body.email.lower().strip()}|{_ip}")

    result = await db.execute(select(User).where(User.email == body.email.lower().strip()))
    user = result.scalar_one_or_none()
    # Always spend the bcrypt cost, even for an unknown email. Skipping it made
    # "no such user" measurably faster than "wrong password", which enumerates
    # registered addresses by response time despite the generic message.
    _verify_password(body.password, user.hashed_password if user else _DUMMY_HASH)
    if not user or not _verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "E-mail ou senha inválidos")
    # Allowlist is checked AFTER password verification with the same generic
    # message, so the response is indistinguishable from a wrong password and
    # reveals neither allowlist membership nor account existence.
    if not _is_login_allowed(user.email):
        logger.warning("login rejected for non-allowlisted account: %s", user.email)
        raise HTTPException(401, "E-mail ou senha inválidos")
    # An explicitly allowlisted operator account is trusted by configuration,
    # so the closed-beta verification gate does not apply to it. Without this
    # an unverified allowlisted address would be locked out by a gate meant for
    # self-serve signups.
    if (
        not user.email_verified
        and user.role != "superadmin"
        and not settings.registration_enabled
        and not _is_allowlisted(user.email)
    ):
        raise HTTPException(403, "Verifique seu e-mail antes de entrar. Link reenviado.")
    if getattr(user, "totp_enabled", False) and user.totp_secret:
        if not body.totp_code:
            raise HTTPException(401, "Código 2FA (TOTP) obrigatório — use backup code se perdeu o celular")
        import pyotp
        totp_ok = pyotp.TOTP(user.totp_secret).verify(body.totp_code, valid_window=1)
        if not totp_ok:
            # tenta backup code
            codes = getattr(user, "totp_backup_codes", None) or []
            if body.totp_code in codes:
                codes.remove(body.totp_code)
                user.totp_backup_codes = codes
                await db.commit()
            else:
                raise HTTPException(401, "Código 2FA inválido")

    token = _create_access_token(user.id, user.org_id)
    refresh = await _issue_refresh(db, user.id)
    return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=user.org_id)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request, body: dict, db: DatabaseBackend = Depends(get_db_backend)):
    """Exchange a refresh token for a new access token + new refresh token."""
    raw = body.get("refresh_token", "")
    if not raw:
        raise HTTPException(422, "refresh_token é obrigatório")

    payload = _verify_jwt_token(raw)
    if not payload:
        raise HTTPException(401, "Token de atualização inválido ou expirado")

    if payload.get("type") != "refresh":
        raise HTTPException(401, "Tipo de token inválido")

    user_id = payload["sub"]

    # A refresh token is only honoured if its jti is in the table, unexpired and
    # not already consumed. Before this, refresh tokens were stateless: a leaked
    # one stayed valid for 30 days and survived logout and password reset, and
    # a replayed one minted unlimited new sessions.
    from aios.db.models import RefreshToken

    jti = payload.get("jti")
    row = await db.get(RefreshToken, jti) if jti else None
    if row is None or row.user_id != user_id:
        logger.warning("refresh rejected: unknown or missing jti for user %s", user_id)
        raise HTTPException(401, "Token de atualização inválido ou expirado")
    now = datetime.now(timezone.utc)
    if _as_utc(row.expires_at) <= now:
        raise HTTPException(401, "Token de atualização inválido ou expirado")
    if row.revoked_at is not None or row.replaced_by is not None:
        # A consumed token being replayed means it was captured. Revoke the
        # whole family: the legitimate client may still be holding the newest.
        logger.warning("refresh replay detected for user %s; revoking all tokens", user_id)
        await _revoke_all_for_user(db, user_id)
        raise HTTPException(401, "Token de atualização inválido ou expirado")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Usuário não encontrado")
    # Re-check on every refresh so revoking allowlist membership (or deleting
    # the row) kills existing sessions immediately instead of at token expiry.
    if not _is_login_allowed(user.email):
        logger.warning("refresh rejected for non-allowlisted account: %s", user.email)
        raise HTTPException(401, "Token de atualização inválido ou expirado")

    token = _create_access_token(user.id, user.org_id)
    # Rotate: consume this jti and issue a fresh one.
    refresh = await _issue_refresh(db, user.id)
    row.revoked_at = now
    row.replaced_by = _new_jti()
    await db.commit()
    return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=user.org_id)


@router.post("/logout")
async def logout(request: Request, db: DatabaseBackend = Depends(get_db_backend)):
    """Revoke every outstanding refresh token for the caller.

    Refresh tokens used to be stateless, so logout was cosmetic: the client
    dropped its copy while a captured one kept minting sessions for 30 days.
    """
    from aios.api.deps import get_current_user

    try:
        user = await get_current_user(request, db)
    except HTTPException:
        # Nothing to revoke if we cannot identify the caller.
        return {"ok": True, "revoked": 0}
    revoked = await _revoke_all_for_user(db, user.id)
    return {"ok": True, "revoked": revoked}


@router.post("/verify-email")
async def verify_email(token: str = Query(...), db: DatabaseBackend = Depends(get_db_backend)):
    """Verify email address using signed token."""
    payload = _verify_jwt_token(token)
    if not payload:
        raise HTTPException(400, "Token de verificação inválido ou expirado")
    if payload.get("purpose") != "email_verify":
        raise HTTPException(400, "Finalidade do token inválida")

    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    if not _is_login_allowed(user.email):
        raise HTTPException(400, "Token de verificação inválido ou expirado")
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
    # Generic response either way; no reset email leaves the server for
    # non-allowlisted addresses.
    if not user or not _is_login_allowed(user.email):
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
    payload = _verify_jwt_token(body.token)
    if not payload:
        raise HTTPException(400, "Token de redefinição inválido ou expirado")
    if payload.get("purpose") != "password_reset":
        raise HTTPException(400, "Finalidade do token inválida")

    _validate_password(body.new_password)
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    if not _is_login_allowed(user.email):
        raise HTTPException(400, "Token de redefinição inválido ou expirado")

    user.hashed_password = _hash_password(body.new_password)
    await db.commit()
    # A password reset is the user's way of saying "assume I was compromised".
    # Every existing session has to die with it, or the attacker's refresh token
    # outlives the reset.
    revoked = await _revoke_all_for_user(db, user.id)
    logger.info("password reset for %s: revoked %d refresh token(s)", user.email, revoked)
    return {"message": "Senha redefinida com sucesso"}


# ─── OAuth ───


_oauth_states: dict[str, dict] = {}  # fallback in-memory
_OAUTH_TTL_SEC = 600  # state valid 10min


_oauth_redis = None


async def _get_oauth_redis():
    global _oauth_redis
    if _oauth_redis is not None:
        return _oauth_redis
    try:
        import redis.asyncio as aioredis
        _oauth_redis = aioredis.from_url(settings.redis_url or "redis://localhost:6379", decode_responses=True)
        await _oauth_redis.ping()
        return _oauth_redis
    except Exception:
        _oauth_redis = None
        return None


async def _oauth_store(state: str, data: dict):
    """Store OAuth state in Redis if available, else in-memory (reuse pool)."""
    global _oauth_redis
    try:
        import json
        r = await _get_oauth_redis()
        if r:
            await r.set(f"oauth:state:{state}", json.dumps(data), ex=_OAUTH_TTL_SEC)
        _oauth_states[state] = data
        if r:
            return
    except Exception:
        _oauth_redis = None
    _oauth_states[state] = data


async def _oauth_pop(state: str) -> dict | None:
    """Pop OAuth state from Redis or in-memory (reuse pool)."""
    global _oauth_redis
    try:
        import json
        r = await _get_oauth_redis()
        if r:
            raw = await r.get(f"oauth:state:{state}")
            if raw:
                await r.delete(f"oauth:state:{state}")
                _oauth_states.pop(state, None)
                return json.loads(raw)
    except Exception:
        _oauth_redis = None
    return _oauth_states.pop(state, None)


async def _oauth_redirect(provider: str, authorize_url: str, client_id: str, scope: str) -> dict:
    """Build OAuth authorize redirect with state."""
    state = secrets.token_urlsafe(32)
    await _oauth_store(state, {"provider": provider, "org_id": None})
    params = f"?client_id={client_id}&redirect_uri={settings.app_url}/api/auth/{provider}/callback&response_type=code&scope={scope}&state={state}"
    return {"authorization_url": authorize_url + params}


async def _oauth_exchange(provider: str, code: str, token_url: str, client_id: str, client_secret: str) -> str:
    """Exchange authorization code for access token. Returns access token."""
    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
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
    stored = await _oauth_pop(state)
    if not stored or stored["provider"] != "google":
        raise HTTPException(400, "Parâmetro de estado inválido")

    token = await _oauth_exchange("google", code,
                                   "https://oauth2.googleapis.com/token",
                                   settings.google_client_id, settings.google_client_secret)

    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
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


@router.get("/google/calendar/login")
async def google_calendar_login(request: Request, db: DatabaseBackend = Depends(get_db_backend)):
    """Redirect to Google OAuth for Calendar (per-org). Requires auth."""
    from aios.api.deps import get_current_user, get_dashboard_user
    user = None
    # Try API auth first, then dashboard cookie
    try:
        user = await get_current_user(request, db)
    except Exception:
        pass
    if not user:
        try:
            user = await get_dashboard_user(request)
        except Exception:
            pass
    if not user:
        # also try request.state set by dashboard_auth (when called via /dashboard)
        uid = getattr(request.state, "user_id", None)
        if uid:
            try:
                user = await db.get(__import__("aios.db.models", fromlist=["User"]).User, uid)
            except Exception:
                pass
    if not user:
        raise HTTPException(401, "Sessão expirada — faça login novamente e recarregue a página")
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(400, "Google OAuth não configurado no servidor — configure AIOS_GOOGLE_CLIENT_ID e AIOS_GOOGLE_CLIENT_SECRET no Coolify → Environment, e adicione redirect URI https://seu-dominio.com/api/auth/google/calendar/callback no Google Cloud Console → Credentials → Authorized redirect URIs")
    state = secrets.token_urlsafe(32)
    # use public base_url (handles Coolify custom domain via proxy headers) with fallback to settings.app_url
    redirect_uri = f"{str(request.base_url).rstrip('/')}/api/auth/google/calendar/callback" if str(request.base_url).startswith("http") else f"{settings.app_url.rstrip('/')}/api/auth/google/calendar/callback"
    # store org context + redirect_uri for callback verification
    await _oauth_store(state, {"provider": "google_calendar", "org_id": user.org_id, "user_id": user.id, "redirect_uri": redirect_uri})
    scope = "openid email profile https://www.googleapis.com/auth/calendar"
    params = f"?client_id={settings.google_client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scope}&state={state}&access_type=offline&prompt=consent"
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth" + params}


@router.get("/google/calendar/callback")
async def google_calendar_callback(code: str, state: str, request: Request, db: DatabaseBackend = Depends(get_db_backend)):
    """Handle Google Calendar OAuth callback — stores refresh token in org secrets."""
    stored = await _oauth_pop(state)
    if not stored or stored["provider"] != "google_calendar":
        raise HTTPException(400, "Parâmetro de estado inválido ou expirado")
    org_id = stored["org_id"]
    redirect_uri = stored.get("redirect_uri") or f"{settings.app_url.rstrip('/')}/api/auth/google/calendar/callback"
    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        data = resp.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in", 3600)
        if not access_token:
            raise HTTPException(400, f"Falha ao obter tokens do Google: {data}")
        # get user email to show who connected
        try:
            uinfo = await client.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {access_token}"})
            email = uinfo.json().get("email", "")
        except Exception:
            email = ""
    # store in org
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organização não encontrada")
    from aios.core.secrets import encrypt_secret
    extra = dict(org.extra_data) if isinstance(org.extra_data, dict) else {}
    secrets = dict(extra.get("secrets", {})) if isinstance(extra.get("secrets"), dict) else {}
    # store tokens encrypted
    enc = dict(extra.get("_secrets_enc", {})) if isinstance(extra.get("_secrets_enc"), dict) else {}
    enc["google_calendar_access_token"] = encrypt_secret(access_token)
    if refresh_token:
        enc["google_calendar_refresh_token"] = encrypt_secret(refresh_token)
    extra["_secrets_enc"] = enc
    secrets["google_calendar_token_expiry"] = str(int(time.time()) + int(expires_in))
    if email:
        secrets["google_calendar_email"] = email
    secrets["google_calendar_connected_at"] = datetime.now(timezone.utc).isoformat()
    extra["secrets"] = secrets
    org.extra_data = extra
    await db.commit()
    # redirect to settings with success
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{settings.app_url}/dashboard/settings?calendar_connected=1", status_code=303)


@router.post("/google/calendar/disconnect")
async def google_calendar_disconnect(request: Request, db: DatabaseBackend = Depends(get_db_backend)):
    """Disconnect Google Calendar — clears stored tokens."""
    from aios.api.deps import get_current_user, get_dashboard_user
    user = None
    try:
        user = await get_current_user(request, db)
    except Exception:
        pass
    if not user:
        try:
            user = await get_dashboard_user(request)
        except Exception:
            pass
    if not user:
        uid = getattr(request.state, "user_id", None)
        if uid:
            try:
                user = await db.get(__import__("aios.db.models", fromlist=["User"]).User, uid)
            except Exception:
                pass
    if not user:
        raise HTTPException(401, "Autentique-se primeiro")
    from aios.db.models import Organization
    org = await db.get(Organization, user.org_id)
    if not org:
        raise HTTPException(404, "Organização não encontrada")
    extra = dict(org.extra_data) if isinstance(org.extra_data, dict) else {}
    secrets = dict(extra.get("secrets", {})) if isinstance(extra.get("secrets"), dict) else {}
    enc = dict(extra.get("_secrets_enc", {})) if isinstance(extra.get("_secrets_enc"), dict) else {}
    for k in ["google_calendar_access_token", "google_calendar_refresh_token", "google_calendar_token_expiry", "google_calendar_email", "google_calendar_connected_at"]:
        secrets.pop(k, None)
        enc.pop(k, None)
    if secrets:
        extra["secrets"] = secrets
    else:
        extra.pop("secrets", None)
    if enc:
        extra["_secrets_enc"] = enc
    else:
        extra.pop("_secrets_enc", None)
    org.extra_data = extra
    await db.commit()
    return {"ok": True}


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
    stored = await _oauth_pop(state)
    if not stored or stored["provider"] != "github":
        raise HTTPException(400, "Parâmetro de estado inválido")

    token = await _oauth_exchange("github", code,
                                   "https://github.com/login/oauth/access_token",
                                   settings.github_client_id, settings.github_client_secret)

    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        data = resp.json()
    provider_user_id = str(data.get("id"))
    email = data.get("email", "")

    # GitHub may not return email in user scope — fetch emails separately
    if not email:
        async with httpx.AsyncClient(timeout=15) as client:
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


@router.get("/totp/setup")
async def totp_setup(request: Request, db: DatabaseBackend = Depends(get_db_backend)):
    """Gera secret TOTP e retorna otpauth:// URL + QR data URI. Requer auth."""
    from aios.api.deps import get_current_user
    user = await get_current_user(request, db)
    import pyotp, base64, io
    secret = pyotp.random_base32()
    # armazenar temporariamente em totp_secret mas ainda não enabled
    user.totp_secret = secret
    await db.commit()
    issuer = getattr(settings, "totp_issuer", "AIOS")
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=issuer)
    # QR como data uri (opcional, sem qrcode lib fallback)
    qr_uri = None
    try:
        import qrcode
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        qr_uri = f"data:image/png;base64,{b64}"
    except Exception:
        qr_uri = uri
    return {"secret": secret, "otpauth_url": uri, "qr_data_uri": qr_uri, "enabled": False}

@router.post("/totp/verify")
async def totp_verify(request: Request, code: str = Query(...), db: DatabaseBackend = Depends(get_db_backend)):
    """Ativa TOTP se código válido — gera 8 backup codes."""
    from aios.api.deps import get_current_user
    user = await get_current_user(request, db)
    if not user.totp_secret:
        raise HTTPException(400, "Gere o setup primeiro")
    import pyotp, secrets
    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(code, valid_window=1):
        # também tenta backup code
        if user.totp_backup_codes and code in user.totp_backup_codes:
            user.totp_backup_codes.remove(code)
            await db.commit()
            return {"enabled": True, "message": "Backup code usado — gere novos se acabarem", "remaining": len(user.totp_backup_codes)}
        raise HTTPException(401, "Código TOTP inválido")
    user.totp_enabled = True
    # gera 8 backup codes se ainda não tem
    if not user.totp_backup_codes:
        user.totp_backup_codes = [secrets.token_hex(4) for _ in range(8)]
    await db.commit()
    return {"enabled": True, "message": "2FA ativado", "backup_codes": user.totp_backup_codes}

@router.post("/totp/disable")
async def totp_disable(request: Request, db: DatabaseBackend = Depends(get_db_backend)):
    from aios.api.deps import get_current_user
    user = await get_current_user(request, db)
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_backup_codes = None
    await db.commit()
    return {"enabled": False}

@router.get("/totp/backup-codes")
async def totp_backup_codes(request: Request, db: DatabaseBackend = Depends(get_db_backend)):
    from aios.api.deps import get_current_user
    user = await get_current_user(request, db)
    if not user.totp_enabled:
        raise HTTPException(400, "2FA não ativo")
    return {"backup_codes": user.totp_backup_codes or [], "remaining": len(user.totp_backup_codes or [])}

async def _oauth_login_or_register(db: DatabaseBackend, provider: str, provider_user_id: str, email: str, name: str) -> TokenResponse:
    """Find existing OAuth account or create user + OAuth account."""
    # OAuth is a login path like any other: a Google/GitHub identity whose
    # email is not allowlisted gets nothing, and no account row is created or
    # linked for it. Without this, any Google account could obtain tokens.
    if not _is_login_allowed(email):
        logger.warning("oauth (%s) rejected for non-allowlisted address", provider)
        raise HTTPException(403, "Acesso restrito — entre em contato com o administrador")
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
            refresh = await _issue_refresh(db, user.id)
            return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=user.org_id)

    # Check if user exists by email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        if not settings.registration_enabled:
            raise HTTPException(403, "Cadastros temporariamente fechados — entre em contato")
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
    refresh = await _issue_refresh(db, user.id)
    return TokenResponse(access_token=token, refresh_token=refresh, user_id=user.id, org_id=user.org_id)
