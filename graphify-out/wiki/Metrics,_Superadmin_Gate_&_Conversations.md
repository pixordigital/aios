# Metrics, Superadmin Gate & Conversations

> 71 nodes · cohesion 0.05

## Key Concepts

- **ToolEngine** (39 connections) — `aios/core/tools.py`
- **dev.py** (22 connections) — `aios/api/dev.py`
- **test_tool_org_scope.py** (14 connections) — `tests/test_tool_org_scope.py`
- **dev_cli.py** (13 connections) — `aios/core/dev_cli.py`
- **TestSqlOrgScoping** (9 connections) — `tests/test_tool_org_scope.py`
- **get_superadmin()** (7 connections) — `aios/api/deps.py`
- **asyncio** (7 connections)
- **dual_build()** (6 connections) — `aios/core/dev_cli.py`
- **dual_review()** (6 connections) — `aios/core/dev_cli.py`
- **run_claude()** (6 connections) — `aios/core/dev_cli.py`
- **run_codex()** (6 connections) — `aios/core/dev_cli.py`
- **SQLQueryTool** (6 connections) — `aios/tools/sql_query.py`
- **TestToolEngineResilience** (6 connections) — `tests/test_crm_tools.py`
- **._tool()** (6 connections) — `tests/test_tool_org_scope.py`
- **build()** (5 connections) — `aios/api/dev.py`
- **claude_run()** (5 connections) — `aios/api/dev.py`
- **codex_run()** (5 connections) — `aios/api/dev.py`
- **PromptIn** (5 connections) — `aios/api/dev.py`
- **post** (5 connections)
- **review()** (5 connections) — `aios/api/dev.py`
- **_validate_cwd()** (5 connections) — `aios/api/dev.py`
- **_run()** (5 connections) — `aios/core/dev_cli.py`
- **.test_execute_path_carries_org()** (5 connections) — `tests/test_crm_tools.py`
- **TestRegistryConsistency** (5 connections) — `tests/test_tool_org_scope.py`
- **TestSuperadminGate** (5 connections) — `tests/test_tool_org_scope.py`
- *... and 46 more nodes in this community*

## Relationships

- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (14 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (10 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (5 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (3 shared connections)
- [CRM Org Isolation Tests](CRM_Org_Isolation_Tests.md) (3 shared connections)
- [CRM Agent Tools](CRM_Agent_Tools.md) (3 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (2 shared connections)
- [Sandbox & Skill Loader](Sandbox_&_Skill_Loader.md) (2 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (1 shared connections)

## Source Files

- `aios/api/analytics.py`
- `aios/api/deps.py`
- `aios/api/dev.py`
- `aios/api/tools.py`
- `aios/core/dev_cli.py`
- `aios/core/tools.py`
- `aios/tools/sql_query.py`
- `docs/YOUTUBE_TODOS_CANAIS_APLICACAO.md`
- `tests/test_crm_tools.py`
- `tests/test_tool_org_scope.py`

## Audit Trail

- EXTRACTED: 162 (89%)
- INFERRED: 20 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*