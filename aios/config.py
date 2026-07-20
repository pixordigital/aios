from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AIOS"
    debug: bool = True
    database_url: str = "sqlite+aiosqlite:///./aios.db"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    app_data_dir: str = "./data"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    dashboard_enabled: bool = True
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_pro: str = ""
    app_url: str = "http://localhost:8777"

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
}

DEFAULT_PLAN = "free"
