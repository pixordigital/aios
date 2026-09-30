# SDK Teams API

> 15 nodes · cohesion 0.14

## Key Concepts

- **test_sdk_imports.py** (10 connections) — `tests/test_sdk_imports.py`
- **TeamsAPI** (8 connections) — `aios/sdk/client.py`
- **test_list_method_does_not_shadow_builtin_in_annotations()** (3 connections) — `tests/test_sdk_imports.py`
- **.teams()** (2 connections) — `aios/sdk/client.py`
- **.__init__()** (2 connections) — `aios/sdk/client.py`
- **test_all_aios_modules_import()** (2 connections) — `tests/test_sdk_imports.py`
- **aios** (1 connections)
- **.assign_agents()** (1 connections) — `aios/sdk/client.py`
- **.create()** (1 connections) — `aios/sdk/client.py`
- **.list()** (1 connections) — `aios/sdk/client.py`
- **pkgutil** (1 connections)
- **SDK import smoke tests. Regression: aios/sdk/client.py defined ``async def…** (1 connections) — `tests/test_sdk_imports.py`
- **Every module must import cleanly; broken ones are silent runtime bombs.** (1 connections) — `tests/test_sdk_imports.py`
- **A .list() method must not break a later list[...] annotation.** (1 connections) — `tests/test_sdk_imports.py`
- **test_sdk_client_imports()** (1 connections) — `tests/test_sdk_imports.py`

## Relationships

- [AIOS SDK Client](AIOS_SDK_Client.md) (2 shared connections)
- [sdk/agent.py +2](sdk-agent.py_+2.md) (1 shared connections)
- [tools/__init__.py +2](tools-__init__.py_+2.md) (1 shared connections)
- [SDK Agent Handle](SDK_Agent_Handle.md) (1 shared connections)
- [SDK Conversations API](SDK_Conversations_API.md) (1 shared connections)

## Source Files

- `aios/sdk/client.py`
- `tests/test_sdk_imports.py`

## Audit Trail

- EXTRACTED: 20 (95%)
- INFERRED: 1 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*