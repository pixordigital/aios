import logging

logger = logging.getLogger(__name__)

SECRETS_KEY = "secrets"
ALLOWED_KEYS = {
    "openrouter_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "s3_bucket",
    "s3_region",
    "s3_access_key",
    "s3_secret_key",
    "s3_endpoint",
    "storage_backend",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from_email",
    "google_client_id",
    "google_client_secret",
    "github_client_id",
    "github_client_secret",
    "stripe_secret_key",
    "stripe_webhook_secret",
    "whatsapp_app_secret",
    "google_calendar_credentials",
    "google_calendar_id",
    "calendar_webhook_url",
    "google_calendar_access_token",
    "google_calendar_refresh_token",
    "google_calendar_token_expiry",
    "google_calendar_email",
    "google_calendar_connected_at",
}

PROVIDER_KEY_MAP = {
    "openrouter": "openrouter_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
}

MODEL_PREFIX_MAP = {
    "openai/": "openrouter_api_key",
    "opencode/": "openrouter_api_key",
    "openai-direct/": "openai_api_key",
    "anthropic-direct/": "anthropic_api_key",
    "anthropic/": "anthropic_api_key",
    "ollama/": None,
}


def model_to_secret_key(model: str) -> str | None:
    for prefix, key in MODEL_PREFIX_MAP.items():
        if model.startswith(prefix):
            return key
    return "openrouter_api_key"


def all_org_secrets(org_extra: dict | None) -> dict[str, str]:
    """Every stored org secret, decrypted.

    Encrypted `_secrets_enc` wins over the legacy cleartext `secrets` dict, so
    rows written before encryption was enforced keep working while any key that
    has since been rewritten comes from the ciphertext store. A single DB dump
    of a new org yields no credentials in the clear.
    """
    if not org_extra or not isinstance(org_extra, dict):
        return {}
    out: dict[str, str] = {}
    plain = org_extra.get(SECRETS_KEY)
    if isinstance(plain, dict):
        out.update({k: v for k, v in plain.items() if isinstance(v, str)})
    enc = org_extra.get("_secrets_enc")
    if isinstance(enc, dict):
        from aios.core.secrets import decrypt_secret

        for k, v in enc.items():
            try:
                out[k] = decrypt_secret(v)
            except Exception:
                # Fail closed on one bad key rather than dropping the whole map.
                out[k] = ""
    return out


def get_org_secret(org_extra: dict | None, key: str) -> str | None:
    # This used to check the cleartext dict FIRST, so a legacy cleartext value
    # shadowed the encrypted one and the encryption was decorative. Read order
    # now lives in all_org_secrets: ciphertext first, cleartext as fallback.
    return all_org_secrets(org_extra).get(key) or None


async def get_org_secret_async(org_id: str, key: str) -> str | None:
    try:
        from aios.db.backend import db_session
        from aios.db.models import Organization
        async with db_session() as db:
            org = await db.get(Organization, org_id)
            if not org:
                return None
            return get_org_secret(org.extra_data, key)
    except Exception:
        return None


def mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return "••••••••" + value[-4:]


def resolve_api_key(model: str, org_extra: dict | None = None, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    if org_extra:
        skey = model_to_secret_key(model)
        if skey:
            v = get_org_secret(org_extra, skey)
            if v:
                return v
    return None
