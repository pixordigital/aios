from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AIOS_", extra="ignore")
    app_name: str = "AIOS"
    debug: bool = True
    crm_webhook_url: str = ""
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
    litellm_api_key: str = "sk-litellm"
    litellm_base_url: str = "http://litellm:4000"
    llm_provider: str = "openrouter"  # openrouter | litellm
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
    evolution_webhook_secret: str = ""  # Evolution webhook HMAC secret
    voice_webhook_secret: str = ""  # Voice webhook HMAC secret
    discord_webhook_secret: str = ""  # Discord webhook HMAC secret
    slack_signing_secret: str = ""  # Slack signing secret for signature verification
    sendgrid_webhook_secret: str = ""  # SendGrid inbound parse webhook secret
    mailgun_webhook_secret: str = ""  # Mailgun webhook secret
    ses_webhook_secret: str = ""  # SES/SNS webhook secret
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
    evolution_server_url: str = "http://evolution:8080"
    evolution_api_key: str = ""
    codex_model: str = "gpt-5.4"
    voice_provider: str = "selfhosted"  # "elevenlabs" | "vapi" | "retell" | "selfhosted"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""
    retell_api_key: str = ""
    retell_agent_id: str = ""
    voice_tts_url: str = "http://voice-tts:8000"  # openedai-speech (Coolify)
    voice_stt_url: str = "http://voice-stt:9000"  # whisper-asr-webservice (Coolify)
    voice_bridge_url: str = ""  # SIP dial bridge (Twilio/LiveKit/Asterisk gateway)
    voice_from_number: str = ""
    livekit_url: str = ""  # wss://... (self-hosted livekit:8080 via compose)
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_tts_ws_url: str = "ws://voice-tts-stream:8001/tts/ws"  # livekit-streaming-tts server
    livekit_tts_engine: str = "xtts"  # xtts (primário) | kokoro (fallback)
    livekit_tts_voice: str = "ptbr"
    kokoro_url: str = "http://voice-tts-kokoro:8880"  # Kokoro-FastAPI fallback
    ollama_model: str = "qwen3:8b"
    voice_llm_model: str = "openai/gpt-4o-mini"  # voice agent LLM: openai/gpt-4o-mini | anthropic/claude-sonnet-4.5 | qwen/qwen-3-235b | ollama/qwen3:8b

    registration_enabled: bool = False  # fechar cadastros — home buttons desabilitados



settings = Settings()

# Stripe price IDs mapped to plan names
STRIPE_PRICE_MAP: dict[str, str] = {}
if settings.stripe_price_starter:
    STRIPE_PRICE_MAP[settings.stripe_price_starter] = "starter"
if settings.stripe_price_pro:
    STRIPE_PRICE_MAP[settings.stripe_price_pro] = "pro"

# ─── Plan limits ───
# max_cost_brl: teto estimado em BRL (USD×5.5) para guardrail — P0-15. Ilimitado = sem teto.
# sla_minutes: tempo máximo humano assumir sem estouro
PLANS = {
    "free": {
        "name": "Gratuito",
        "max_agents": 2,
        "max_teams": 1,
        "max_messages_per_day": 100,
        "max_tokens_per_month": 500_000,
        "max_cost_brl": 10,
        "sla_minutes": 15,
        "channels": ["web"],
        "max_evolution_instances": 0,
    },
    "starter": {
        "name": "Starter",
        "max_agents": 10,
        "max_teams": 3,
        "max_messages_per_day": 500,
        "max_tokens_per_month": 5_000_000,
        "max_cost_brl": 100,
        "sla_minutes": 10,
        "channels": ["web", "evolution"],
        "max_evolution_instances": 1,
    },
    "pro": {
        "name": "Pro",
        "max_agents": 50,
        "max_teams": 10,
        "max_messages_per_day": 5000,
        "max_tokens_per_month": 50_000_000,
        "max_cost_brl": 800,
        "sla_minutes": 5,
        "channels": ["web", "evolution", "email", "slack", "telegram", "discord", "voice"],
        "max_evolution_instances": 3,
    },
    "enterprise": {
        "name": "Enterprise",
        "max_agents": 500,
        "max_teams": 100,
        "max_messages_per_day": 50000,
        "max_tokens_per_month": 500_000_000,
        "max_cost_brl": 8000,
        "sla_minutes": 2,
        "channels": "__all__",
        "max_evolution_instances": 10,
    },
    "unlimited": {
        "name": "Ilimitado",
        "max_agents": 999999,
        "max_teams": 999999,
        "max_messages_per_day": 999999,
        "max_tokens_per_month": 999999999,
        "max_cost_brl": 999999,
        "sla_minutes": 1,
        "channels": "__all__",
        "max_evolution_instances": 999999,
    },
}

DEFAULT_PLAN = "free"
