# Agent Type Tool Tests

> 17 nodes · cohesion 0.18

## Key Concepts

- **AsyncClient** (11 connections)
- **TestAgentTypes** (7 connections) — `tests/test_agent_types.py`
- **parametrize** (5 connections)
- **.test_create_agent_type()** (5 connections) — `tests/test_agent_types.py`
- **.test_agent_type_has_template()** (4 connections) — `tests/test_agent_types.py`
- **.test_agent_type_message_flow()** (4 connections) — `tests/test_agent_types.py`
- **.test_agent_type_with_tools()** (4 connections) — `tests/test_agent_types.py`
- **.test_deploy_agent_type()** (4 connections) — `tests/test_agent_types.py`
- **Test Execution** (3 connections) — `PRODUCTION_READINESS_REPORT.md`
- **.test_pro_plan_max_agents()** (3 connections) — `tests/test_agent_types.py`
- **Test each agent type with tool configuration.** (1 connections) — `tests/test_agent_types.py`
- **Pro plan should allow more agents.** (1 connections) — `tests/test_agent_types.py`
- **Test each agent type can be created and deployed.** (1 connections) — `tests/test_agent_types.py`
- **Test creating each agent type.** (1 connections) — `tests/test_agent_types.py`
- **Test deploying each agent type.** (1 connections) — `tests/test_agent_types.py`
- **Test each agent type gets template defaults (except custom which is blank).** (1 connections) — `tests/test_agent_types.py`
- **Test full message flow with each agent type.** (1 connections) — `tests/test_agent_types.py`

## Relationships

- [Agent Input Validation Tests](Agent_Input_Validation_Tests.md) (4 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (3 shared connections)
- [Test webhook endpoints for channels that have  +2](Test_webhook_endpoints_for_channels_that_have__+2.md) (1 shared connections)
- [CyberSec Meeting & Prod Readiness](CyberSec_Meeting_&_Prod_Readiness.md) (1 shared connections)

## Source Files

- `PRODUCTION_READINESS_REPORT.md`
- `tests/test_agent_types.py`

## Audit Trail

- EXTRACTED: 32 (97%)
- INFERRED: 1 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*