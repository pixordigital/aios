# DB Engine & Session

> 20 nodes · cohesion 0.12

## Key Concepts

- **engine.py** (17 connections) — `aios/db/engine.py`
- **alembic/env.py** (12 connections) — `alembic/env.py`
- **init_db()** (8 connections) — `aios/db/engine.py`
- **migrations/env.py** (7 connections) — `migrations/env.py`
- **sqlalchemy_ext_asyncio** (4 connections)
- **sqlalchemy_orm** (4 connections)
- **run_async_migrations()** (3 connections) — `alembic/env.py`
- **logging_config** (3 connections)
- **get_db()** (2 connections) — `aios/db/engine.py`
- **_is_postgres()** (2 connections) — `aios/db/engine.py`
- **.on_startup()** (2 connections) — `aios/tasks/worker.py`
- **do_run_migrations()** (2 connections) — `alembic/env.py`
- **run_migrations_online()** (2 connections) — `alembic/env.py`
- **run_migrations_offline()** (2 connections) — `migrations/env.py`
- **run_migrations_online()** (2 connections) — `migrations/env.py`
- **Alembic env — async SQLAlchemy for Postgres/SQLite.** (1 connections) — `alembic/env.py`
- **run_migrations_offline()** (1 connections) — `alembic/env.py`
- **Alembic environment config — supports SQLite + PostgreSQL.** (1 connections) — `migrations/env.py`
- **Run migrations in 'offline' mode.** (1 connections) — `migrations/env.py`
- **Run migrations in 'online' mode.** (1 connections) — `migrations/env.py`

## Relationships

- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (6 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (5 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (4 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (3 shared connections)
- [AsyncSession Delegation](AsyncSession_Delegation.md) (3 shared connections)
- [Secrets Envelope](Secrets_Envelope.md) (1 shared connections)
- [Transactional Outbox](Transactional_Outbox.md) (1 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (1 shared connections)
- [Vector Extension & CRM Versions](Vector_Extension_&_CRM_Versions.md) (1 shared connections)
- [coolify-one-click.md +2](coolify-one-click.md_+2.md) (1 shared connections)
- [ARQ Job Alias Wrapper](ARQ_Job_Alias_Wrapper.md) (1 shared connections)

## Source Files

- `aios/db/engine.py`
- `aios/tasks/worker.py`
- `alembic/env.py`
- `migrations/env.py`

## Audit Trail

- EXTRACTED: 52 (95%)
- INFERRED: 3 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*