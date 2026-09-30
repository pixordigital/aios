# Agent Telemetry

> 12 nodes · cohesion 0.17

## Key Concepts

- **AgentTelemetry** (9 connections) — `aios/core/telemetry.py`
- **.record()** (3 connections) — `aios/core/telemetry.py`
- **.get_all_agents_summary()** (2 connections) — `aios/core/telemetry.py`
- **.get_metrics_for_agent()** (2 connections) — `aios/core/telemetry.py`
- **.get_org_summary()** (2 connections) — `aios/core/telemetry.py`
- **_current_hour()** (2 connections) — `aios/core/telemetry.py`
- **.__init__()** (1 connections) — `aios/core/telemetry.py`
- **Get per-agent summary for an org.** (1 connections) — `aios/core/telemetry.py`
- **Track per-agent metrics in-memory, flush to DB periodically.** (1 connections) — `aios/core/telemetry.py`
- **Record a metric data point for an agent.** (1 connections) — `aios/core/telemetry.py`
- **Get recent metrics for an agent.** (1 connections) — `aios/core/telemetry.py`
- **Get aggregated metrics for an org.** (1 connections) — `aios/core/telemetry.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (1 shared connections)

## Source Files

- `aios/core/telemetry.py`

## Audit Trail

- EXTRACTED: 14 (93%)
- INFERRED: 1 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*