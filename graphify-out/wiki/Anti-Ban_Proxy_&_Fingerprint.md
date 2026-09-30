# Anti-Ban Proxy & Fingerprint

> 12 nodes · cohesion 0.18

## Key Concepts

- **proxy_pool.py** (6 connections) — `aios/core/whatsapp/anti_ban/proxy_pool.py`
- **ProxyPoolManager** (5 connections) — `aios/core/whatsapp/anti_ban/proxy_pool.py`
- **ipaddress** (4 connections)
- **random** (4 connections)
- **.get_proxy()** (3 connections) — `aios/core/whatsapp/anti_ban/proxy_pool.py`
- **fingerprint_rotator.py** (2 connections) — `aios/core/whatsapp/anti_ban/fingerprint_rotator.py`
- **.ipv6_for_instance()** (2 connections) — `aios/core/whatsapp/anti_ban/proxy_pool.py`
- **fingerprint_for()** (1 connections) — `aios/core/whatsapp/anti_ban/fingerprint_rotator.py`
- **.health()** (1 connections) — `aios/core/whatsapp/anti_ban/proxy_pool.py`
- **.__init__()** (1 connections) — `aios/core/whatsapp/anti_ban/proxy_pool.py`
- **Proxy pool híbrido $0: Tier1 IPv6 /64 Hetzner + Tier2 Squid IPv4 + Tier3 direct.** (1 connections) — `aios/core/whatsapp/anti_ban/proxy_pool.py`
- **Retorna dict httpx proxy ou None (direct).** (1 connections) — `aios/core/whatsapp/anti_ban/proxy_pool.py`

## Relationships

- [WhatsApp Health & Ban Detector](WhatsApp_Health_&_Ban_Detector.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [Evolution Key Rotation & IP Allowlist](Evolution_Key_Rotation_&_IP_Allowlist.md) (1 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (1 shared connections)
- [SSRF Guard](SSRF_Guard.md) (1 shared connections)
- [Evolution Channel (Baileys+Meta)](Evolution_Channel_Baileys+Meta.md) (1 shared connections)

## Source Files

- `aios/core/whatsapp/anti_ban/fingerprint_rotator.py`
- `aios/core/whatsapp/anti_ban/proxy_pool.py`

## Audit Trail

- EXTRACTED: 19 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*