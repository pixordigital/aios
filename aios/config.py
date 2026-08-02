from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AIOS"
    debug: bool = True
    database_url: str = "sqlite+aiosqlite:///./aios.db"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    storage_backend: str = "local"  # "local" | "s3"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_endpoint: str = ""  # for Supabase Storage, R2, MinIO
    db_backend: str = "sqlalchemy"  # "sqlalchemy" | "convex"
    db_replica_backend: str = ""  # failover backend type, empty = no failover
    convex_url: str = ""
    convex_admin_key: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    redis_url: str = ""  # e.g. redis://:password@host:6379/0
    redis_password: str = ""  # used when redis_url lacks embedded creds
    app_data_dir: str = "./data"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60  # reduced from 1440 for security
    jwt_refresh_expire_days: int = 30
    log_format: str = "json"  # "text" | "json"
    https_only: bool = True

    cors_origins: str = ""  # comma-separated, defaults to app_url in non-debug
    rate_limit_per_minute: int = 60
    password_bcrypt_rounds: int = 12
    dashboard_enabled: bool = True
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_pro: str = ""
    app_url: str = "http://localhost:8777"
    admin_master_key: str = ""  # set in production — used for fleet management auth
    whatsapp_app_secret: str = ""  # Meta app secret for webhook signature verification
    whatsapp_verify_token: str = ""  # Meta webhook subscribe verification token
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    sentry_dsn: str = ""

    class Config:
        env_file = ".env"
        env_prefix = "AIOS_"


settings = Settings()

# Stripe price IDs mapped to plan names
STRIPE_PRICE_MAP: dict[str, str] = {}
if settings.stripe_price_starter:
    STRIPE_PRICE_MAP[settings.stripe_price_starter] = "starter"
if settings.stripe_price_pro:
    STRIPE_PRICE_MAP[settings.stripe_price_pro] = "pro"

# ─── Plan limits ───

PLANS = {
    "free": {
        "max_agents": 2,
        "max_teams": 1,
        "max_messages_per_day": 100,
        "max_tokens_per_month": 500_000,
        "channels": ["web"],
    },
    "starter": {
        "max_agents": 10,
        "max_teams": 3,
        "max_messages_per_day": 500,
        "max_tokens_per_month": 5_000_000,
        "channels": ["web", "whatsapp"],
    },
    "pro": {
        "max_agents": 50,
        "max_teams": 10,
        "max_messages_per_day": 5000,
        "max_tokens_per_month": 50_000_000,
        "channels": ["web", "whatsapp", "email", "slack", "telegram", "discord"],
    },
    "enterprise": {
        "max_agents": 500,
        "max_teams": 100,
        "max_messages_per_day": 50000,
        "max_tokens_per_month": 500_000_000,
        "channels": "__all__",
    },
    "unlimited": {
        "max_agents": 999999,
        "max_teams": 999999,
        "max_messages_per_day": 999999,
        "max_tokens_per_month": 999999999,
        "channels": "__all__",
    },
}

DEFAULT_PLAN = "free"
