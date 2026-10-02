import httpx, logging
from aios.core.whatsapp.config import settings
logger = logging.getLogger(__name__)
async def vault_encrypt(plaintext: str) -> str:
    # Fallback to local envelope if Vault unavailable
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.post(f"{settings.vault_url}/v1/transit/encrypt/aios", headers={"X-Vault-Token": settings.vault_token}, json={"plaintext": plaintext})
            if r.status_code==200: return r.json()["data"]["ciphertext"]
    except Exception as e: logger.warning("vault encrypt fallback %s", e)
    from .envelope import encrypt
    return encrypt(plaintext)
