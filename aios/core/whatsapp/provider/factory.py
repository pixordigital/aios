from .base import WhatsAppProvider, ProviderType
from .evolution_baileys import EvolutionBaileysProvider
from .evolution_cloud import EvolutionCloudProvider
from .evolution_coexistence import EvolutionCoexistenceProvider

_providers: dict[ProviderType, WhatsAppProvider] = {
    "baileys": EvolutionBaileysProvider(),
    "cloud": EvolutionCloudProvider(),
    "coexistence": EvolutionCoexistenceProvider(),
}

def get_provider(provider: ProviderType = "baileys") -> WhatsAppProvider:
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
