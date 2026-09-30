# Channel API Tests

> 22 nodes · cohesion 0.13

## Key Concepts

- **TestChannels** (11 connections) — `tests/test_channels.py`
- **AsyncClient** (9 connections)
- **test_channels.py** (3 connections) — `tests/test_channels.py`
- **.test_create_channel()** (3 connections) — `tests/test_channels.py`
- **.test_delete_channel()** (3 connections) — `tests/test_channels.py`
- **.test_get_channel()** (3 connections) — `tests/test_channels.py`
- **.test_list_channels()** (3 connections) — `tests/test_channels.py`
- **.test_test_channel()** (3 connections) — `tests/test_channels.py`
- **.test_test_channel_blocks_private_url()** (3 connections) — `tests/test_channels.py`
- **.test_test_channel_requires_auth()** (3 connections) — `tests/test_channels.py`
- **.test_toggle_channel()** (3 connections) — `tests/test_channels.py`
- **.test_update_channel()** (3 connections) — `tests/test_channels.py`
- **Test channel connection without saving.** (1 connections) — `tests/test_channels.py`
- **Test creating a channel.** (1 connections) — `tests/test_channels.py`
- **Unauthenticated channel test must be rejected.** (1 connections) — `tests/test_channels.py`
- **Channel test with internal URL must be blocked (SSRF guard).** (1 connections) — `tests/test_channels.py`
- **Test listing channels.** (1 connections) — `tests/test_channels.py`
- **Test getting a single channel.** (1 connections) — `tests/test_channels.py`
- **Test updating a channel.** (1 connections) — `tests/test_channels.py`
- **Test deleting a channel.** (1 connections) — `tests/test_channels.py`
- **Channel CRUD and management tests.** (1 connections) — `tests/test_channels.py`
- **Test toggling channel active status.** (1 connections) — `tests/test_channels.py`

## Relationships

- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)

## Source Files

- `tests/test_channels.py`

## Audit Trail

- EXTRACTED: 31 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*