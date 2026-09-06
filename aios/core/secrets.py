import base64
import hashlib

from aios.config import settings


def _key() -> bytes:
    raw = settings.jwt_secret.encode()
    digest = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_secret(plain: str) -> str:
    from cryptography.fernet import Fernet
    return Fernet(_key()).encrypt(plain.encode()).decode()

def decrypt_secret(token: str) -> str:
    from cryptography.fernet import Fernet
    return Fernet(_key()).decrypt(token.encode()).decode()

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
            try:
                out[k] = "enc:" + encrypt_secret(str(v)) if v else v
            except Exception:
                out[k] = v
        elif isinstance(v, dict):
            out[k] = encrypt_channel_config(v)
        else:
            out[k] = v
    return out

def decrypt_channel_config(config: dict) -> dict:
    out = {}
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
