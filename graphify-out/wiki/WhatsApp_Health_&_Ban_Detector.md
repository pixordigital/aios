# WhatsApp Health & Ban Detector

> 20 nodes · cohesion 0.17

## Key Concepts

- **service.py** (11 connections) — `aios/core/whatsapp/service.py`
- **send_via_gateway()** (10 connections) — `aios/core/whatsapp/service.py`
- **anti_ban/__init__.py** (9 connections) — `aios/core/whatsapp/anti_ban/__init__.py`
- **get_provider()** (8 connections) — `aios/core/whatsapp/provider/factory.py`
- **ban_detector.py** (6 connections) — `aios/core/whatsapp/anti_ban/ban_detector.py`
- **risk_score()** (6 connections) — `aios/core/whatsapp/anti_ban/ban_detector.py`
- **compute()** (6 connections) — `aios/core/whatsapp/anti_ban/health_monitor.py`
- **human_simulator.py** (6 connections) — `aios/core/whatsapp/anti_ban/human_simulator.py`
- **human_delay()** (5 connections) — `aios/core/whatsapp/anti_ban/human_simulator.py`
- **soak.py** (5 connections) — `deploy/chaos/soak.py`
- **health_monitor.py** (4 connections) — `aios/core/whatsapp/anti_ban/health_monitor.py`
- **whatsapp_health()** (3 connections) — `aios/api/whatsapp.py`
- **should_quarantine()** (2 connections) — `aios/core/whatsapp/anti_ban/ban_detector.py`
- **soak()** (2 connections) — `deploy/chaos/soak.py`
- **test_health_green()** (2 connections) — `tests/whatsapp/test_gateway.py`
- **Delay log-normal simulando humano: score alto = mais rápido.** (1 connections) — `aios/core/whatsapp/anti_ban/human_simulator.py`
- **typing_duration()** (1 connections) — `aios/core/whatsapp/anti_ban/human_simulator.py`
- **Pipeline anti-ban enxuto: delay humano + provider send + ban check.** (1 connections) — `aios/core/whatsapp/service.py`
- **k6 / chaos stub: baseline 100 inst, 10k msg/min** (1 connections) — `deploy/chaos/soak.py`
- **ProviderType** (1 connections)

## Relationships

- [Settings & Channel Health](Settings_&_Channel_Health.md) (6 shared connections)
- [WhatsApp Gateway API](WhatsApp_Gateway_API.md) (5 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (4 shared connections)
- [migration_advisor.py +2](migration_advisor.py_+2.md) (3 shared connections)
- [WhatsApp Warmup Curves](WhatsApp_Warmup_Curves.md) (3 shared connections)
- [Anti-Ban Proxy & Fingerprint](Anti-Ban_Proxy_&_Fingerprint.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (1 shared connections)

## Source Files

- `aios/api/whatsapp.py`
- `aios/core/whatsapp/anti_ban/__init__.py`
- `aios/core/whatsapp/anti_ban/ban_detector.py`
- `aios/core/whatsapp/anti_ban/health_monitor.py`
- `aios/core/whatsapp/anti_ban/human_simulator.py`
- `aios/core/whatsapp/provider/factory.py`
- `aios/core/whatsapp/service.py`
- `deploy/chaos/soak.py`
- `tests/whatsapp/test_gateway.py`

## Audit Trail

- EXTRACTED: 56 (98%)
- INFERRED: 1 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*