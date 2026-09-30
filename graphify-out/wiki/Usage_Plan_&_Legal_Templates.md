# Usage Plan & Legal Templates

> 25 nodes · cohesion 0.09

## Key Concepts

- **test_migrations.py** (16 connections) — `tests/test_migrations.py`
- **UsageRecord** (12 connections) — `aios/db/models.py`
- **Enterprise Legal Templates — AIOS** (5 connections) — `docs/ENTERPRISE_LEGAL_TEMPLATES.md`
- **.plan()** (3 connections) — `aios/core/workflow.py`
- **PRINCÍPIO INEGOCIÁVEL — AIOS** (3 connections) — `docs/PRINCIPIO_VERDADE.md`
- **Regra** (3 connections) — `docs/PRINCIPIO_VERDADE.md`
- **_src()** (3 connections) — `tests/test_migrations.py`
- **ENTERPRISE_LEGAL_TEMPLATES.md** (2 connections) — `docs/ENTERPRISE_LEGAL_TEMPLATES.md`
- **1. MSA — Master Service Agreement (resumo)** (2 connections) — `docs/ENTERPRISE_LEGAL_TEMPLATES.md`
- **PRINCIPIO_VERDADE.md** (2 connections) — `docs/PRINCIPIO_VERDADE.md`
- **Check (antes de cada deploy da home)** (2 connections) — `docs/PRINCIPIO_VERDADE.md`
- **test_blacklist_migration_guards_added_columns()** (2 connections) — `tests/test_migrations.py`
- **test_create_table_migrations_are_guarded()** (2 connections) — `tests/test_migrations.py`
- **test_inbound_populates_provider_message_id()** (2 connections) — `tests/test_migrations.py`
- **test_message_model_declares_dedup_constraint()** (2 connections) — `tests/test_migrations.py`
- **test_model_declares_the_constraint()** (2 connections) — `tests/test_migrations.py`
- **3. SLA 99,9% — Enterprise** (1 connections) — `docs/ENTERPRISE_LEGAL_TEMPLATES.md`
- **4. Checklist de Assinatura** (1 connections) — `docs/ENTERPRISE_LEGAL_TEMPLATES.md`
- **Migration hygiene tests. Regression: two migrations created tables/columns…** (1 connections) — `tests/test_migrations.py`
- **Redeliveries duplicated Message rows because channel_message_id stayed NULL.…** (1 connections) — `tests/test_migrations.py`
- **test_every_migration_parses()** (1 connections) — `tests/test_migrations.py`
- **test_messages_dedup_migration_exists()** (1 connections) — `tests/test_migrations.py`
- **test_no_duplicate_revision_ids()** (1 connections) — `tests/test_migrations.py`
- **test_usage_records_unique_migration_exists()** (1 connections) — `tests/test_migrations.py`
- **test_versions_dir_exists()** (1 connections) — `tests/test_migrations.py`

## Relationships

- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (6 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (3 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (2 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (2 shared connections)
- [CRM2 Routes](CRM2_Routes.md) (1 shared connections)
- [ESAA Planner & Hooks](ESAA_Planner_&_Hooks.md) (1 shared connections)
- [Vector Extension & CRM Versions](Vector_Extension_&_CRM_Versions.md) (1 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)
- [Sandbox & Skill Loader](Sandbox_&_Skill_Loader.md) (1 shared connections)

## Source Files

- `aios/core/workflow.py`
- `aios/db/models.py`
- `docs/ENTERPRISE_LEGAL_TEMPLATES.md`
- `docs/PRINCIPIO_VERDADE.md`
- `tests/test_migrations.py`

## Audit Trail

- EXTRACTED: 33 (73%)
- INFERRED: 12 (27%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*