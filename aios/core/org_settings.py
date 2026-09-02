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
    "zernio_webhook_secret",
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


def get_org_secret(org_extra: dict | None, key: str) -> str | None:
    if not org_extra or not isinstance(org_extra, dict):
        return None
    secrets = org_extra.get(SECRETS_KEY, {})
    if not isinstance(secrets, dict):
        return None
    val = secrets.get(key)
    return val if val else None


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
