from typing import Any
import base64
import hashlib
import logging

logger = logging.getLogger(__name__)

from aios.config import settings


def _key() -> bytes:
    # A dedicated key when the operator sets one. Otherwise the legacy
    # derivation from jwt_secret, because every already-stored credential was
    # encrypted that way and changing the default would orphan them all.
    raw = (getattr(settings, "encryption_key", "") or settings.jwt_secret).encode()
    digest = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_secret(plain: str) -> str:
    from cryptography.fernet import Fernet
    return Fernet(_key()).encrypt(plain.encode()).decode()

def _legacy_key() -> bytes:
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def decrypt_secret(token: str) -> str:
    from cryptography import fernet as _fernet_mod
    from cryptography.fernet import Fernet

    try:
        return Fernet(_key()).decrypt(token.encode()).decode()
    except _fernet_mod.InvalidToken:
        # Rows written before a dedicated encryption_key was set used the
        # legacy jwt_secret derivation. Trying it here makes rotation a
        # config change instead of a data loss event; anything else still
        # raises, because swallowing it would return wrong secrets silently.
        return Fernet(_legacy_key()).decrypt(token.encode()).decode()

def get_org_secrets(org_extra: dict) -> dict:
    enc = (org_extra or {}).get("_secrets_enc", {})
    out = {}
    for k, v in enc.items():
        try:
            out[k] = decrypt_secret(v)
        except Exception:
            out[k] = ""
    return out

def set_org_secret(org, key: str, value: str):
    data = dict(org.extra_data or {})
    enc = dict(data.get("_secrets_enc") or {})
    enc[key] = encrypt_secret(value)
    data["_secrets_enc"] = enc
    org.extra_data = data

_SENSITIVE_KEYS = {"access_token","api_key","bot_token","password","secret","signing_secret","token","apikey","apiKey"}

def encrypt_channel_config(config: dict) -> dict:
    out = {}
    for k,v in (config or {}).items():
        if k in _SENSITIVE_KEYS or any(s in k.lower() for s in ["token","key","secret","password"]):
            if not v:
                out[k] = v
                continue
            try:
                out[k] = "enc:" + encrypt_secret(str(v))
            except Exception:
                # Fail CLOSED. Storing the plaintext on error meant a misconfigured
                # or missing encryption key silently persisted API tokens and SMTP
                # passwords in cleartext -- a key problem would look like success.
                # Losing a channel credential is recoverable; leaking it is not.
                logger.error(
                    "channel secret %r failed to encrypt -- refusing to store in "
                    "plaintext; set AIOS_ENCRYPTION_KEY", k,
                )
                raise
        elif isinstance(v, dict):
            out[k] = encrypt_channel_config(v)
        else:
            out[k] = v
    return out

def decrypt_channel_config(config: dict) -> dict:
    # values can be str or a nested dict (this recurses), so not dict[str, str]
    out: dict[str, Any] = {}
    for k,v in (config or {}).items():
        if isinstance(v, str) and v.startswith("enc:"):
            try:
                out[k] = decrypt_secret(v[4:])
            except Exception:
                out[k] = v
        elif isinstance(v, dict):
            out[k] = decrypt_channel_config(v)
        else:
            out[k] = v
    return out
