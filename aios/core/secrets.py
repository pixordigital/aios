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
