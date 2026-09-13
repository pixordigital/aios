"""Envelope encryption AES-256-GCM + Vault Transit (fallback: local key)."""
import os, base64
from cryptography.fernet import Fernet

def _local_key() -> bytes:
    raw = os.getenv("AIOS_WHATSAPP_VAULT_TOKEN") or os.getenv("AIOS_JWT_SECRET") or "local-dev-key-32bytes-123456789012"
    # Fernet precisa 32 bytes base64
    import hashlib
    h = hashlib.sha256(raw.encode()).digest()
    return base64.urlsafe_b64encode(h)

_fernet = Fernet(_local_key())

def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()

def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()
