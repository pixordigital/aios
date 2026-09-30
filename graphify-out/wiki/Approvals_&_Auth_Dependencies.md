# Approvals & Auth Dependencies

> 65 nodes · cohesion 0.08

## Key Concepts

- **sqlalchemy** (86 connections)
- **db/backend.py** (64 connections) — `aios/db/backend.py`
- **deps.py** (57 connections) — `aios/api/deps.py`
- **get_current_user()** (48 connections) — `aios/api/deps.py`
- **fastapi** (46 connections)
- **router.py** (38 connections) — `aios/api/router.py`
- **get_db_backend()** (33 connections) — `aios/db/backend.py`
- **get_org_id()** (30 connections) — `aios/api/deps.py`
- **files.py** (25 connections) — `aios/api/files.py`
- **teams.py** (25 connections) — `aios/api/teams.py`
- **api/tools.py** (23 connections) — `aios/api/tools.py`
- **versions.py** (19 connections) — `aios/api/versions.py`
- **gdpr.py** (18 connections) — `aios/api/gdpr.py`
- **mcp.py** (17 connections) — `aios/api/mcp.py`
- **promptlab.py** (17 connections) — `aios/api/promptlab.py`
- **api/secrets.py** (16 connections) — `aios/api/secrets.py`
- **integrations.py** (15 connections) — `aios/api/integrations.py`
- **knowledge.py** (14 connections) — `aios/api/knowledge.py`
- **api/license.py** (14 connections) — `aios/api/license.py`
- **threads.py** (14 connections) — `aios/api/threads.py`
- **approvals.py** (13 connections) — `aios/api/approvals.py`
- **register_dynamic_tool()** (10 connections) — `aios/tools/dynamic.py`
- **sqlalchemy_backend.py** (9 connections) — `aios/db/backends/sqlalchemy_backend.py`
- **mcp_call()** (7 connections) — `aios/api/mcp.py`
- **create_tool()** (7 connections) — `aios/api/tools.py`
- *... and 40 more nodes in this community*

## Relationships

- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (53 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (32 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (30 shared connections)
- [Alembic Migrations](Alembic_Migrations.md) (25 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (25 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (23 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (18 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (18 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (17 shared connections)
- [Metrics, Superadmin Gate & Conversations](Metrics,_Superadmin_Gate_&_Conversations.md) (14 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (10 shared connections)
- [Agents CRUD & Deploy](Agents_CRUD_&_Deploy.md) (8 shared connections)

## Source Files

- `aios/api/approvals.py`
- `aios/api/deps.py`
- `aios/api/files.py`
- `aios/api/gdpr.py`
- `aios/api/integrations.py`
- `aios/api/knowledge.py`
- `aios/api/license.py`
- `aios/api/mcp.py`
- `aios/api/promptlab.py`
- `aios/api/router.py`
- `aios/api/secrets.py`
- `aios/api/teams.py`
- `aios/api/threads.py`
- `aios/api/tools.py`
- `aios/api/versions.py`
- `aios/core/rag.py`
- `aios/core/tools.py`
- `aios/db/backend.py`
- `aios/db/backends/sqlalchemy_backend.py`
- `aios/tools/dynamic.py`

## Audit Trail

- EXTRACTED: 578 (94%)
- INFERRED: 37 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*