"""Proxy pool híbrido $0: Tier1 IPv6 /64 Hetzner + Tier2 Squid IPv4 + Tier3 direct."""
import ipaddress, random, logging
logger = logging.getLogger(__name__)

class ProxyPoolManager:
    def __init__(self, ipv6_prefix: str = "2a01:4f8:1c1a:924a::/64", squid_url: str = "http://squid:3128"):
        self.prefix = ipaddress.IPv6Network(ipv6_prefix) if ipv6_prefix else None
        self.squid_url = squid_url

    def ipv6_for_instance(self, instance: str) -> str | None:
        if not self.prefix:
            return None
        # determinístico por instance: hash -> host part
        h = abs(hash(instance)) % (2**32)
        # ::1 + offset dentro do /64
        base = int(self.prefix.network_address)
        addr = ipaddress.IPv6Address(base + (h % (2**32)) + 1)
        return str(addr)

    def get_proxy(self, instance: str, risk: int = 0) -> dict | None:
        """Retorna dict httpx proxy ou None (direct)."""
        if risk >= 70:
            # alto risco -> IPv6 dedicado
            ipv6 = self.ipv6_for_instance(instance)
            # Squid escuta em [::]:3128 e faz outgoing via IPv6 dedicado se configurado
            return {"http://": self.squid_url, "https://": self.squid_url} if ipv6 else None
        if risk >= 40:
            return {"http://": self.squid_url, "https://": self.squid_url}
        return None  # Tier3 direct para maduras

    def health(self) -> dict:
        return {"ipv6_prefix": str(self.prefix) if self.prefix else None, "squid": self.squid_url}

pool = ProxyPoolManager()
