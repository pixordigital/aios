# WhatsApp Gateway API

> 16 nodes · cohesion 0.22

## Key Concepts

- **whatsapp.py** (30 connections) — `aios/api/whatsapp.py`
- **whatsapp_send()** (9 connections) — `aios/api/whatsapp.py`
- **evolution_webhook()** (7 connections) — `aios/api/whatsapp.py`
- **post** (4 connections)
- **whatsapp_call()** (4 connections) — `aios/api/whatsapp.py`
- **CallBody** (3 connections) — `aios/api/whatsapp.py`
- **migration_check()** (3 connections) — `aios/api/whatsapp.py`
- **SendBody** (3 connections) — `aios/api/whatsapp.py`
- **rate_limiter.py** (3 connections) — `aios/core/whatsapp/anti_ban/rate_limiter.py`
- **allow()** (3 connections) — `aios/core/whatsapp/anti_ban/rate_limiter.py`
- **record_429()** (3 connections) — `aios/core/whatsapp/anti_ban/rate_limiter.py`
- **validate()** (3 connections) — `aios/core/whatsapp/webhook_validator.py`
- **metrics_summary()** (2 connections) — `aios/api/whatsapp.py`
- **BaseModel** (2 connections)
- **Request** (2 connections)
- **.is_smb_echo()** (2 connections) — `aios/core/whatsapp/provider/evolution_coexistence.py`

## Relationships

- [WhatsApp Health & Ban Detector](WhatsApp_Health_&_Ban_Detector.md) (5 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (5 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (3 shared connections)
- [Secrets Envelope](Secrets_Envelope.md) (2 shared connections)
- [Call Router](Call_Router.md) (2 shared connections)
- [IVR, PII Redaction & Call Routing](IVR,_PII_Redaction_&_Call_Routing.md) (2 shared connections)
- [Evolution Key Rotation & IP Allowlist](Evolution_Key_Rotation_&_IP_Allowlist.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (2 shared connections)
- [migration_advisor.py +2](migration_advisor.py_+2.md) (2 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)
- [Alembic Migrations](Alembic_Migrations.md) (1 shared connections)

## Source Files

- `aios/api/whatsapp.py`
- `aios/core/whatsapp/anti_ban/rate_limiter.py`
- `aios/core/whatsapp/provider/evolution_coexistence.py`
- `aios/core/whatsapp/webhook_validator.py`

## Audit Trail

- EXTRACTED: 55 (96%)
- INFERRED: 2 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*