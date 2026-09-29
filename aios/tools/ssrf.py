"""SSRF guard for tools that fetch user- or agent-supplied URLs.

Shared by http_get, http_request and etl_url so the protection lives in one
place. etl_url previously had none: it followed redirects and would fetch
http://169.254.169.254/ or internal services, then index the response into the
knowledge base where the agent could read it back out.
"""

import ipaddress
import socket
from urllib.parse import urlparse

# Cloud metadata + RFC1918 + loopback + link-local + unique-local.
_PRIVATE_BLOCKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # AWS/GCP/Azure/DO metadata
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
]

ALLOWED_SCHEMES = ("http", "https")


def is_private_host(host: str) -> bool:
    """True when host resolves to a private/internal address. Fails closed."""
    if not host:
        return True
    try:
        addr = socket.getaddrinfo(host, 80)[0][4][0]
    except Exception:
        return True
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _PRIVATE_BLOCKS)


def check_url(url: str, *, allow_private: bool = False) -> str | None:
    """Return an error string if the URL must not be fetched, else None."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "invalid url"
    if parsed.scheme not in ALLOWED_SCHEMES:
        return f"scheme not allowed: {parsed.scheme or '(none)'}"
    if not parsed.hostname:
        return "url has no host"
    if not allow_private and is_private_host(parsed.hostname):
        return f"private/internal host blocked: {parsed.hostname}"
    return None
