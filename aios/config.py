from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AIOS_", extra="ignore")
    app_name: str = "AIOS"
    # Secure by default. This used to default to True, and that single flag
    # disabled the rate-limit middleware, switched CORS to allow_origins=["*"]
    # WITH allow_credentials=True, and skipped the production DB check -- so any
    # deployment that forgot AIOS_DEBUG came up wide open. Opt in explicitly.
    debug: bool = False
    # USD -> BRL. This was hardcoded as the literal 5.5 in ~40 places across
    # limits.py, billing.py, whatsapp_pricing.py and the dashboard templates, so
    # every cost figure in the product moved with the real exchange rate and
    # nobody could change it without editing a dozen files.
    usd_brl_rate: float = 5.5
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
    s3_sse_enabled: bool = True  # Server-Side Encryption (SSE-S3)
    s3_versioning_enabled: bool = True  # Bucket versioning for ransomware protection
    db_backend: str = "sqlalchemy"  # "sqlalchemy"
    db_replica_backend: str = ""  # failover backend type, empty = no failover
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    litellm_api_key: str = "sk-litellm"
    litellm_base_url: str = "http://litellm:4000"
    llm_provider: str = "openrouter"  # openrouter | litellm
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    redis_url: str = ""  # e.g. redis://user:password@host:6379/0 SASL
    redis_username: str = ""  # SASL username (default = "default" quando só password)
    redis_password: str = ""  # used when redis_url lacks embedded creds (SASL)
    app_data_dir: str = "./data"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60  # reduced from 1440 for security
    jwt_refresh_expire_days: int = 30
    jwt_ed25519_private_key: str = ""  # Ed25519 private key (base64) for JWT signing
    jwt_ed25519_public_key: str = ""   # Ed25519 public key (base64) for JWT verification
    encryption_key: str = ""  # at-rest secret encryption; when empty, derived from jwt_secret (legacy)
    jwt_key_rotation_days: int = 90    # days before JWT key rotation
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
    usage_webhook_url: str = ""  # Metered billing webhook (voice_minutes, llm_tokens)
    usage_webhook_secret: str = ""  # HMAC secret for usage webhook
    slack_signing_secret: str = ""  # Slack signing secret for signature verification
    # SendGrid inbound parse is Ed25519/ECDSA over (timestamp + payload) and is
    # verified with the app's PUBLIC key — a shared secret cannot check it, so
    # there is no secret field for it and the endpoint refuses loudly.
    # Only Mailgun's scheme is checkable with a shared secret.
    mailgun_webhook_secret: str = ""  # Mailgun webhook secret
    # SES/SNS likewise signs with the platform's RSA key, not a shared secret.
    siem_webhook_url: str = ""  # SIEM webhook URL for audit log forwarding
    siem_webhook_secret: str = ""  # SIEM webhook HMAC secret
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
    # Where Evolution POSTs inbound events. Default is the internal Docker network
    # address so signed payloads never cross the internet. Override when Evolution
    # runs on a different host.
    evolution_webhook_base: str = "http://app:8777/api/evolution/webhook"
    evolution_ip_allowlist: str = ""  # comma-separated IPs/CIDRs allowed to access Evolution API (e.g. "10.0.0.0/8,192.168.1.0/24")
    evolution_api_key_rotation_days: int = 30  # days before API key rotation recommended
    # Outbound bubble batching: texts to the same recipient inside the window
    # are joined with a blank line and sent as ONE WhatsApp message (one
    # per-message fee instead of N). Templates, interactive and media messages
    # never join a batch — they flush it and go alone, in order.
    whatsapp_batch_enabled: bool = True
    whatsapp_batch_window_sec: float = 2.0
    whatsapp_batch_max_messages: int = 5
    whatsapp_batch_max_chars: int = 3800  # merged cap, under Meta's 4096 limit
    codex_model: str = "gpt-5.4"
    voice_provider: str = "selfhosted"  # "elevenlabs" | "vapi" | "retell" | "selfhosted"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""
    retell_api_key: str = ""
    retell_agent_id: str = ""
    # Deployed TTS is Kokoro (docker-compose service voice-tts-kokoro). The old
    # default pointed at "http://voice-tts:8000", a service that is not deployed
    # anywhere, so an unset VOICE_TTS_URL produced a connection error against a
    # host that could never exist.
    voice_tts_url: str = "http://voice-tts-kokoro:8880/v1"
    # Empty by default on purpose. No STT service runs unless the opt-in
    # `voice-stt` compose profile is started, so a non-empty default made
    # VoiceChannel.test() print "+ STT configurado" and /api/voice/providers
    # publish a URL that never resolves — every transcription then failed with a
    # DNS error. Empty takes the honest "sem stt_url nem openai key" path.
    voice_stt_url: str = ""
    voice_bridge_url: str = ""  # SIP dial bridge (Twilio/Asterisk gateway)
    voice_from_number: str = ""
    kokoro_url: str = "http://voice-tts-kokoro:8880"  # Kokoro-FastAPI TTS
    ollama_model: str = "qwen3:8b"
    voice_llm_model: str = "openai/gpt-4o-mini"  # voice agent LLM: openai/gpt-4o-mini | anthropic/claude-sonnet-4.5 | qwen/qwen-3-235b | ollama/qwen3:8b

    whatsapp_coexistence_enabled: bool = True  # Coexistence (App + Cloud mesmo número)
    whatsapp_embedded_signup_app_id: str = ""  # Meta App ID para Embedded Signup coexistence
    # Meta App credentials. app_secret is used only to compute appsecret_proof on
    # Graph API calls; it is not a tenant credential.
    whatsapp_app_id: str = ""
    whatsapp_app_secret: str = ""

    registration_enabled: bool = False  # fechar cadastros — home buttons desabilitados
    # Single-operator lockdown. Comma-separated emails allowed to authenticate
    # (password login, dashboard login, refresh, OAuth). Empty = open to any
    # registered user (legacy behavior); set AIOS_LOGIN_ALLOWLIST in production.
    # Env: AIOS_LOGIN_ALLOWLIST
    login_allowlist: str = ""

    # ─── Internal mode (P1 pivot) ───
    # True = ferramenta interna de times de agentes: ignora quotas PLANS,
    # gates de CRM/billing e limites de instâncias. Tracking de uso continua.
    internal_mode: bool = False  # env AIOS_INTERNAL_MODE

    # ─── Calendar (P3) ───
    google_calendar_credentials: str = ""  # JSON service account inline ou path (env GOOGLE_CALENDAR_CREDENTIALS / AIOS_GOOGLE_CALENDAR_CREDENTIALS)
    google_calendar_id: str = "primary"  # calendarId (env GOOGLE_CALENDAR_ID)
    # ─── Cal.com self-hosted (sales scheduling) ───
    # API key from the self-hosted instance: Settings > Security (cal_ test /
    # cal_live_ prod). Empty = the cal_booking tool fails closed.
    calcom_api_url: str = "http://calcom-api:80"  # internal service name (env AIOS_CALCOM_API_URL)
    calcom_api_key: str = ""  # env AIOS_CALCOM_API_KEY
    calcom_api_version: str = "2024-08-13"  # env AIOS_CALCOM_API_VERSION (slots pin 2024-09-04)
    calcom_event_type_id: int = 0  # default event type for SDR bookings (env AIOS_CALCOM_EVENT_TYPE_ID)
    calcom_timezone: str = "America/Sao_Paulo"  # env AIOS_CALCOM_TIMEZONE
    calendar_webhook_url: str = ""  # webhook Calendly/Zapier/n8n (env CALENDAR_WEBHOOK_URL / AIOS_CALENDAR_WEBHOOK_URL)
    # AIOS ↔ ARVO integration (Fase 1A — feature-flag off por padrão)
    arvo_integration_enabled: bool = False
    arvo_base_url: str = ""
    arvo_service_key_id: str = ""
    arvo_service_key: str = ""



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
        "channels": ["web", "evolution", "email", "slack", "telegram", "voice"],
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
