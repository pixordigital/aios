from pydantic_settings import BaseSettings
from pydantic import Field

class WhatsAppGatewaySettings(BaseSettings):
    model_config = {"env_prefix": "AIOS_WHATSAPP_", "extra": "ignore"}
    # Evolution engine
    evolution_url: str = Field(default="http://evolution:8080")
    evolution_api_key: str = Field(default="")
    # Proxy pool (self-hosted)
    proxy_enabled: bool = True
    proxy_squid_url: str = "http://squid:3128"  # Tier 2
    proxy_ipv6_prefix: str = "2a01:4f8:1c1a:924a::/64"  # Tier 1: Hetzner IPv6
    # Anti-ban
    warmup_curve: str = "balanced"  # conservative|balanced|aggressive
    rate_limit_per_minute: int = 20
    human_delay_min_ms: int = 800
    human_delay_max_ms: int = 3500
    # KMS / Vault
    vault_url: str = "http://vault:8200"
    vault_token: str = ""
    # SeaweedFS (S3 compat)
    s3_endpoint: str = "http://seaweedfs:8333"
    s3_bucket: str = "aios-whatsapp"
    # Risk thresholds
    ban_risk_warn: int = 70
    ban_risk_critical: int = 85

settings = WhatsAppGatewaySettings()
