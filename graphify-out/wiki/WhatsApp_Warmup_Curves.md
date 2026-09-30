# WhatsApp Warmup Curves

> 60 nodes · cohesion 0.05

## Key Concepts

- **score_from_events()** (20 connections) — `aios/core/whatsapp/anti_ban/risk.py`
- **anti_ban/signals.py** (13 connections) — `aios/core/whatsapp/anti_ban/signals.py`
- **TestScoring** (13 connections) — `tests/test_ban_risk.py`
- **dashboard_data.py** (10 connections) — `aios/core/whatsapp/anti_ban/dashboard_data.py`
- **gather_counts()** (10 connections) — `aios/core/whatsapp/anti_ban/signals.py`
- **looks_like_ban()** (9 connections) — `aios/core/whatsapp/anti_ban/signals.py`
- **test_ban_risk.py** (9 connections) — `tests/test_ban_risk.py`
- **instance_report()** (8 connections) — `aios/core/whatsapp/anti_ban/dashboard_data.py`
- **risk.py** (6 connections) — `aios/core/whatsapp/anti_ban/risk.py`
- **is_quarantined()** (6 connections) — `aios/core/whatsapp/anti_ban/signals.py`
- **TestBanDetection** (6 connections) — `tests/test_ban_risk.py`
- **TestQuarantineGate** (6 connections) — `tests/test_ban_risk.py`
- **connection_warmer.py** (5 connections) — `aios/core/whatsapp/anti_ban/connection_warmer.py`
- **daily_limit()** (5 connections) — `aios/core/whatsapp/anti_ban/connection_warmer.py`
- **.test_fails_open_without_db()** (5 connections) — `tests/test_ban_risk.py`
- **org_report()** (4 connections) — `aios/core/whatsapp/anti_ban/dashboard_data.py`
- **.test_not_quarantined_on_noise()** (4 connections) — `tests/test_ban_risk.py`
- **is_allowed()** (3 connections) — `aios/core/whatsapp/anti_ban/connection_warmer.py`
- **RiskReport** (3 connections) — `aios/core/whatsapp/anti_ban/risk.py`
- **asyncio** (3 connections)
- **.test_403_without_ban_words_is_not_a_ban()** (3 connections) — `tests/test_ban_risk.py`
- **.test_quarantined_on_corroborated_evidence()** (3 connections) — `tests/test_ban_risk.py`
- **feed()** (3 connections) — `tests/test_ban_risk.py`
- **.test_one_429_is_noise()** (3 connections) — `tests/test_ban_risk.py`
- **.test_one_repeating_signal_never_quarantines()** (3 connections) — `tests/test_ban_risk.py`
- *... and 35 more nodes in this community*

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (7 shared connections)
- [Evolution Channel (Baileys+Meta)](Evolution_Channel_Baileys+Meta.md) (5 shared connections)
- [WhatsApp Health & Ban Detector](WhatsApp_Health_&_Ban_Detector.md) (3 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (2 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)

## Source Files

- `aios/core/whatsapp/anti_ban/connection_warmer.py`
- `aios/core/whatsapp/anti_ban/dashboard_data.py`
- `aios/core/whatsapp/anti_ban/risk.py`
- `aios/core/whatsapp/anti_ban/signals.py`
- `tests/test_ban_risk.py`

## Audit Trail

- EXTRACTED: 113 (97%)
- INFERRED: 4 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*