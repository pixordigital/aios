# Secrets Envelope

> 18 nodes · cohesion 0.18

## Key Concepts

- **consent.py** (10 connections) — `aios/core/whatsapp/lgpd/consent.py`
- **envelope.py** (9 connections) — `aios/core/whatsapp/kms/envelope.py`
- **lgpd/audit.py** (8 connections) — `aios/core/whatsapp/lgpd/audit.py`
- **encrypt()** (6 connections) — `aios/core/whatsapp/kms/envelope.py`
- **record_consent()** (6 connections) — `aios/core/whatsapp/lgpd/consent.py`
- **vault_client.py** (5 connections) — `aios/core/whatsapp/kms/vault_client.py`
- **lgpd/__init__.py** (5 connections) — `aios/core/whatsapp/lgpd/__init__.py`
- **check_consent()** (4 connections) — `aios/core/whatsapp/lgpd/consent.py`
- **base64** (4 connections)
- **kms/__init__.py** (3 connections) — `aios/core/whatsapp/kms/__init__.py`
- **log_action()** (3 connections) — `aios/core/whatsapp/lgpd/audit.py`
- **_hash()** (3 connections) — `aios/core/whatsapp/lgpd/consent.py`
- **decrypt()** (2 connections) — `aios/core/whatsapp/kms/envelope.py`
- **vault_encrypt()** (2 connections) — `aios/core/whatsapp/kms/vault_client.py`
- **_local_key()** (1 connections) — `aios/core/whatsapp/kms/envelope.py`
- **Envelope encryption AES-256-GCM + Vault Transit (fallback: local key).** (1 connections) — `aios/core/whatsapp/kms/envelope.py`
- **# TODO: persist to lgpd_audit_log WORM (MinIO/SeaweedFS) Phase B** (1 connections) — `aios/core/whatsapp/lgpd/audit.py`
- **cryptography_fernet** (1 connections)

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (3 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (2 shared connections)
- [SPARC Workflow Engine](SPARC_Workflow_Engine.md) (2 shared connections)
- [WhatsApp Gateway API](WhatsApp_Gateway_API.md) (2 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [whatsapp/config.py +2](whatsapp-config.py_+2.md) (1 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (1 shared connections)
- [DB Engine & Session](DB_Engine_&_Session.md) (1 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (1 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (1 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (1 shared connections)

## Source Files

- `aios/core/whatsapp/kms/__init__.py`
- `aios/core/whatsapp/kms/envelope.py`
- `aios/core/whatsapp/kms/vault_client.py`
- `aios/core/whatsapp/lgpd/__init__.py`
- `aios/core/whatsapp/lgpd/audit.py`
- `aios/core/whatsapp/lgpd/consent.py`

## Audit Trail

- EXTRACTED: 45 (96%)
- INFERRED: 2 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*