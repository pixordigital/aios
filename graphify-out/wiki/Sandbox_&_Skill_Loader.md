# Sandbox & Skill Loader

> 30 nodes · cohesion 0.07

## Key Concepts

- **skill_loader.py** (11 connections) — `aios/core/skill_loader.py`
- **pathlib** (11 connections)
- **code.py** (9 connections) — `aios/tools/code.py`
- **run_isolated()** (8 connections) — `aios/core/sandbox.py`
- **calculator.py** (8 connections) — `aios/tools/calculator.py`
- **python_sandbox.py** (8 connections) — `aios/tools/python_sandbox.py`
- **re** (8 connections)
- **sandbox.py** (6 connections) — `aios/core/sandbox.py`
- **.execute()** (3 connections) — `aios/core/tools.py`
- **ToolExecutionError** (3 connections) — `aios/core/tools.py`
- **CalculatorTool** (3 connections) — `aios/tools/calculator.py`
- **_safe_eval()** (3 connections) — `aios/tools/calculator.py`
- **CodeTool** (3 connections) — `aios/tools/code.py`
- **PythonSandboxTool** (3 connections) — `aios/tools/python_sandbox.py`
- **SkillSection** (2 connections) — `aios/core/skill_loader.py`
- **.run()** (2 connections) — `aios/tools/calculator.py`
- **CodeInput** (2 connections) — `aios/tools/code.py`
- **.run()** (2 connections) — `aios/tools/code.py`
- **PythonSandboxInput** (2 connections) — `aios/tools/python_sandbox.py`
- **.run()** (2 connections) — `aios/tools/python_sandbox.py`
- **_preexec()** (1 connections) — `aios/core/sandbox.py`
- **Skill Loader — runtime skill injection from project files (AGENTS.md,…** (1 connections) — `aios/core/skill_loader.py`
- **A parsed skill section from a markdown file.** (1 connections) — `aios/core/skill_loader.py`
- **Exception** (1 connections)
- **CalculatorInput** (1 connections) — `aios/tools/calculator.py`
- *... and 5 more nodes in this community*

## Relationships

- [Tool Base Abstraction](Tool_Base_Abstraction.md) (16 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (11 shared connections)
- [Skill Markdown Loader](Skill_Markdown_Loader.md) (2 shared connections)
- [Metrics, Superadmin Gate & Conversations](Metrics,_Superadmin_Gate_&_Conversations.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)
- [Agents CRUD & Deploy](Agents_CRUD_&_Deploy.md) (1 shared connections)
- [Alembic Migrations](Alembic_Migrations.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [Cron Ticks (Backup, CRM, Pending)](Cron_Ticks_Backup,_CRM,_Pending.md) (1 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (1 shared connections)
- [Storage Backends](Storage_Backends.md) (1 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (1 shared connections)

## Source Files

- `aios/core/sandbox.py`
- `aios/core/skill_loader.py`
- `aios/core/tools.py`
- `aios/tools/calculator.py`
- `aios/tools/code.py`
- `aios/tools/python_sandbox.py`

## Audit Trail

- EXTRACTED: 76 (99%)
- INFERRED: 1 (1%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*