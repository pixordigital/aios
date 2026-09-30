# Google Calendar Tools

> 45 nodes · cohesion 0.07

## Key Concepts

- **_install_google_stub()** (13 connections) — `tests/test_calendar_tools.py`
- **test_calendar_tools.py** (12 connections) — `tests/test_calendar_tools.py`
- **CalendarTool** (9 connections) — `aios/tools/calendar.py`
- **TestUnconfigured** (9 connections) — `tests/test_calendar_tools.py`
- **CalendarAvailabilityTool** (8 connections) — `aios/tools/calendar.py`
- **CalendarListTool** (8 connections) — `aios/tools/calendar.py`
- **TestConfigured** (8 connections) — `tests/test_calendar_tools.py`
- **asyncio** (7 connections)
- **_parse_iso()** (5 connections) — `aios/tools/calendar.py`
- **_resolve_google()** (5 connections) — `aios/tools/calendar.py`
- **.run()** (4 connections) — `aios/tools/calendar.py`
- **.run()** (4 connections) — `aios/tools/calendar.py`
- **.run()** (4 connections) — `aios/tools/calendar.py`
- **_service()** (4 connections) — `aios/tools/calendar.py`
- **.test_availability_computes_free_gaps()** (4 connections) — `tests/test_calendar_tools.py`
- **.test_bad_datetime_rejected()** (4 connections) — `tests/test_calendar_tools.py`
- **.test_create_returns_real_link()** (4 connections) — `tests/test_calendar_tools.py`
- **.test_list_returns_events()** (4 connections) — `tests/test_calendar_tools.py`
- **query()** (3 connections) — `tests/test_calendar_tools.py`
- **.test_availability_fails_closed()** (3 connections) — `tests/test_calendar_tools.py`
- **.test_create_fails_closed()** (3 connections) — `tests/test_calendar_tools.py`
- **.test_list_fails_closed()** (3 connections) — `tests/test_calendar_tools.py`
- **_query()** (2 connections) — `aios/tools/calendar.py`
- **_list()** (2 connections) — `aios/tools/calendar.py`
- **_insert()** (2 connections) — `aios/tools/calendar.py`
- *... and 20 more nodes in this community*

## Relationships

- [Tool Base Abstraction](Tool_Base_Abstraction.md) (11 shared connections)
- [Logging Config](Logging_Config.md) (1 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)

## Source Files

- `aios/tools/calendar.py`
- `aios/tools/web_search.py`
- `tests/test_calendar_tools.py`

## Audit Trail

- EXTRACTED: 76 (87%)
- INFERRED: 11 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*