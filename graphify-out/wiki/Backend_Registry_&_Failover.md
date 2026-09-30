# Backend Registry & Failover

> 10 nodes · cohesion 0.20

## Key Concepts

- **BackendRegistry** (9 connections) — `aios/db/backend.py`
- **.active()** (2 connections) — `aios/db/backend.py`
- **.check_failover()** (2 connections) — `aios/db/backend.py`
- **.init()** (2 connections) — `aios/db/backend.py`
- **.close_all()** (1 connections) — `aios/db/backend.py`
- **.__init__()** (1 connections) — `aios/db/backend.py`
- **.is_failed_over()** (1 connections) — `aios/db/backend.py`
- **.summary()** (1 connections) — `aios/db/backend.py`
- **Holds primary + replica backends and handles failover.** (1 connections) — `aios/db/backend.py`
- **Check primary health. If primary down and replica exists, switch. Returns True…** (1 connections) — `aios/db/backend.py`

## Relationships

- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (2 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (1 shared connections)

## Source Files

- `aios/db/backend.py`

## Audit Trail

- EXTRACTED: 12 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*