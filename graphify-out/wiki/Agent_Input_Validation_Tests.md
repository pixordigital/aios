# Agent Input Validation Tests

> 10 nodes · cohesion 0.20

## Key Concepts

- **TestAgentValidation** (6 connections) — `tests/test_agent_types.py`
- **.test_invalid_agent_type_rejected()** (3 connections) — `tests/test_agent_types.py`
- **.test_invalid_max_tokens_rejected()** (3 connections) — `tests/test_agent_types.py`
- **.test_invalid_temperature_rejected()** (3 connections) — `tests/test_agent_types.py`
- **.test_invalid_tool_rejected()** (3 connections) — `tests/test_agent_types.py`
- **Test agent input validation.** (1 connections) — `tests/test_agent_types.py`
- **Invalid agent type should be rejected.** (1 connections) — `tests/test_agent_types.py`
- **Temperature outside 0-2 should be rejected.** (1 connections) — `tests/test_agent_types.py`
- **Max tokens outside 256-16384 should be rejected.** (1 connections) — `tests/test_agent_types.py`
- **Invalid tool should be rejected.** (1 connections) — `tests/test_agent_types.py`

## Relationships

- [Agent Type Tool Tests](Agent_Type_Tool_Tests.md) (4 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (1 shared connections)

## Source Files

- `tests/test_agent_types.py`

## Audit Trail

- EXTRACTED: 14 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*