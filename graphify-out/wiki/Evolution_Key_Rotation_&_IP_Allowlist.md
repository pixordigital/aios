# Evolution Key Rotation & IP Allowlist

> 27 nodes · cohesion 0.13

## Key Concepts

- **evolution_api.py** (18 connections) — `aios/core/evolution_api.py`
- **evo_delete()** (11 connections) — `aios/core/evolution_api.py`
- **_base()** (9 connections) — `aios/core/evolution_api.py`
- **evo_create_instance()** (9 connections) — `aios/core/evolution_api.py`
- **evo_fetch_instances()** (9 connections) — `aios/core/evolution_api.py`
- **_evo_headers()** (9 connections) — `aios/core/evolution_api.py`
- **_get_ip_allowlist()** (7 connections) — `aios/core/evolution_api.py`
- **evo_connect()** (6 connections) — `aios/core/evolution_api.py`
- **evo_send_text()** (6 connections) — `aios/core/evolution_api.py`
- **evo_logout()** (5 connections) — `aios/core/evolution_api.py`
- **evo_restart()** (5 connections) — `aios/core/evolution_api.py`
- **evo_status()** (5 connections) — `aios/core/evolution_api.py`
- **get_evolution_key_rotation_status()** (4 connections) — `aios/core/evolution_api.py`
- **evolution_connect_page()** (4 connections) — `aios/dashboard/app.py`
- **evolution_ip_allowlist()** (3 connections) — `aios/api/admin_api.py`
- **evolution_key_status()** (3 connections) — `aios/api/admin_api.py`
- **check_evolution_ip_allowed()** (3 connections) — `aios/core/evolution_api.py`
- **Get Evolution API key rotation status.** (2 connections) — `aios/api/admin_api.py`
- **.create_instance()** (2 connections) — `aios/core/whatsapp/provider/evolution_baileys.py`
- **.delete_instance()** (2 connections) — `aios/core/whatsapp/provider/evolution_baileys.py`
- **.delete_instance()** (2 connections) — `aios/core/whatsapp/provider/evolution_cloud.py`
- **Get Evolution API IP allowlist configuration.** (1 connections) — `aios/api/admin_api.py`
- **C4: Envia texto simples via Evolution Baileys.** (1 connections) — `aios/core/evolution_api.py`
- **Parse comma-separated IP allowlist from settings.** (1 connections) — `aios/core/evolution_api.py`
- **Check if client IP is in the Evolution API allowlist.** (1 connections) — `aios/core/evolution_api.py`
- *... and 2 more nodes in this community*

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (19 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (9 shared connections)
- [Admin Fleet & DLQ](Admin_Fleet_&_DLQ.md) (4 shared connections)
- [WhatsApp Gateway API](WhatsApp_Gateway_API.md) (2 shared connections)
- [Cron Ticks (Backup, CRM, Pending)](Cron_Ticks_Backup,_CRM,_Pending.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [Anti-Ban Proxy & Fingerprint](Anti-Ban_Proxy_&_Fingerprint.md) (1 shared connections)
- [SPARC Workflow Engine](SPARC_Workflow_Engine.md) (1 shared connections)

## Source Files

- `aios/api/admin_api.py`
- `aios/core/evolution_api.py`
- `aios/core/whatsapp/provider/evolution_baileys.py`
- `aios/core/whatsapp/provider/evolution_cloud.py`
- `aios/dashboard/app.py`

## Audit Trail

- EXTRACTED: 85 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*