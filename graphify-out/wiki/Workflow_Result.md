# Workflow Result

> 13 nodes · cohesion 0.15

## Key Concepts

- **_FakeClient** (7 connections) — `tests/test_slack_channel.py`
- **WorkflowResult** (5 connections) — `aios/core/workflow.py`
- **_FakeResponse** (4 connections) — `tests/test_slack_channel.py`
- **_factory()** (3 connections) — `tests/test_slack_channel.py`
- **.ok()** (2 connections) — `aios/core/workflow.py`
- **.post()** (2 connections) — `tests/test_slack_channel.py`
- **.__init__()** (1 connections) — `aios/core/workflow.py`
- **.__aenter__()** (1 connections) — `tests/test_slack_channel.py`
- **.__aexit__()** (1 connections) — `tests/test_slack_channel.py`
- **.__init__()** (1 connections) — `tests/test_slack_channel.py`
- **.__init__()** (1 connections) — `tests/test_slack_channel.py`
- **.json()** (1 connections) — `tests/test_slack_channel.py`
- **Stands in for httpx.AsyncClient in a `async with` block.** (1 connections) — `tests/test_slack_channel.py`

## Relationships

- [Slack Token & Delivery](Slack_Token_&_Delivery.md) (3 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)

## Source Files

- `aios/core/workflow.py`
- `tests/test_slack_channel.py`

## Audit Trail

- EXTRACTED: 16 (89%)
- INFERRED: 2 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*