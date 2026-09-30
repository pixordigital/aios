# RFC7807 Error Model

> 16 nodes · cohesion 0.17

## Key Concepts

- **errors.py** (11 connections) — `aios/api/errors.py`
- **_problem()** (9 connections) — `aios/api/errors.py`
- **register_error_handlers()** (7 connections) — `aios/api/errors.py`
- **fastapi_responses** (5 connections)
- **ProblemResponse** (3 connections) — `aios/api/errors.py`
- **http_exception_handler()** (3 connections) — `aios/api/errors.py`
- **FastAPI** (2 connections)
- **global_handler()** (2 connections) — `aios/api/errors.py`
- **validation_handler()** (2 connections) — `aios/api/errors.py`
- **_translate_detail()** (2 connections) — `aios/api/errors.py`
- **BaseModel** (1 connections)
- **RFC 7807 (Problem Details) error responses. All API errors return: { "type":…** (1 connections) — `aios/api/errors.py`
- **Build a Problem Details dict. Falls back to a default title by status.** (1 connections) — `aios/api/errors.py`
- **Mount error handlers returning RFC 7807 problems.** (1 connections) — `aios/api/errors.py`
- **fastapi_exceptions** (1 connections)
- **starlette_exceptions** (1 connections)

## Relationships

- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (4 shared connections)
- [Middleware Stack](Middleware_Stack.md) (2 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (1 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (1 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (1 shared connections)

## Source Files

- `aios/api/errors.py`

## Audit Trail

- EXTRACTED: 31 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*