from .base import WhatsAppProvider
from .evolution_baileys import EvolutionBaileysProvider
from .evolution_cloud import EvolutionCloudProvider
from .evolution_coexistence import EvolutionCoexistenceProvider

# Keyed by plain str, not ProviderType: get_provider defaults unknown names to
# baileys, so a Literal key type would force every caller to pre-validate what
# this function already handles.
_providers: dict[str, WhatsAppProvider] = {
    "baileys": EvolutionBaileysProvider(),
    "cloud": EvolutionCloudProvider(),
    "coexistence": EvolutionCoexistenceProvider(),
}

def get_provider(provider: str = "baileys") -> WhatsAppProvider:
    return _providers.get(provider, _providers["baileys"])

def get_provider_for_instance(instance_cfg: dict | None) -> WhatsAppProvider:
    """Escolhe provider por config da instância; default baileys. Coexistence detecta is_on_biz_app."""
    if not instance_cfg:
        return _providers["baileys"]
    if instance_cfg.get("is_on_biz_app") or instance_cfg.get("isOnBizApp"):
        return _providers["coexistence"]
    p = instance_cfg.get("provider") or instance_cfg.get("integration") or "baileys"
    pl = str(p).lower()
    if "coexist" in pl:
        return _providers["coexistence"]
    if "cloud" in pl:
        return _providers["cloud"]
    return _providers["baileys"]
