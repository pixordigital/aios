# Each manager/orchestrator channel routes to it +2

> 8 nodes · cohesion 0.32

## Key Concepts

- **TestSlackChannelRouting** (5 connections) — `tests/test_slack_channel.py`
- **._pick()** (4 connections) — `tests/test_slack_channel.py`
- **.test_matches_slack_channel_id()** (3 connections) — `tests/test_slack_channel.py`
- **.test_unmatched_falls_back_to_first()** (3 connections) — `tests/test_slack_channel.py`
- **Each manager/orchestrator channel routes to its own connection.** (1 connections) — `tests/test_slack_channel.py`
- **Mirror of _find_connection's selection logic.** (1 connections) — `tests/test_slack_channel.py`
- **__init__()** (1 connections) — `tests/test_slack_channel.py`
- **__init__()** (1 connections) — `tests/test_slack_channel.py`

## Relationships

- [Slack Token & Delivery](Slack_Token_&_Delivery.md) (1 shared connections)

## Source Files

- `tests/test_slack_channel.py`

## Audit Trail

- EXTRACTED: 10 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*