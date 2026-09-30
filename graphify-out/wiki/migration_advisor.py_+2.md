# migration_advisor.py +2

> 9 nodes · cohesion 0.36

## Key Concepts

- **test_gateway.py** (10 connections) — `tests/whatsapp/test_gateway.py`
- **evaluate()** (6 connections) — `aios/core/whatsapp/migration_advisor.py`
- **migration_advisor.py** (4 connections) — `aios/core/whatsapp/migration_advisor.py`
- **quality_monitor.py** (3 connections) — `aios/core/whatsapp/voice/quality_monitor.py`
- **mos_from_metrics()** (3 connections) — `aios/core/whatsapp/voice/quality_monitor.py`
- **MigrationRecommendation** (2 connections) — `aios/core/whatsapp/migration_advisor.py`
- **test_migration_warn()** (2 connections) — `tests/whatsapp/test_gateway.py`
- **test_mos()** (2 connections) — `tests/whatsapp/test_gateway.py`
- **fallback_chain()** (1 connections) — `aios/core/whatsapp/voice/quality_monitor.py`

## Relationships

- [WhatsApp Health & Ban Detector](WhatsApp_Health_&_Ban_Detector.md) (3 shared connections)
- [WhatsApp Gateway API](WhatsApp_Gateway_API.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)

## Source Files

- `aios/core/whatsapp/migration_advisor.py`
- `aios/core/whatsapp/voice/quality_monitor.py`
- `tests/whatsapp/test_gateway.py`

## Audit Trail

- EXTRACTED: 20 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*