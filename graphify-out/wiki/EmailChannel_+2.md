# EmailChannel +2

> 8 nodes · cohesion 0.32

## Key Concepts

- **EmailChannel** (12 connections) — `aios/channels/email_.py`
- **._poll_loop()** (6 connections) — `aios/channels/email_.py`
- **.send()** (3 connections) — `aios/channels/email_.py`
- **.start()** (2 connections) — `aios/channels/email_.py`
- **.__init__()** (1 connections) — `aios/channels/email_.py`
- **.stop()** (1 connections) — `aios/channels/email_.py`
- **.test()** (1 connections) — `aios/channels/email_.py`
- **Poll IMAP inbox every 30s for new messages.** (1 connections) — `aios/channels/email_.py`

## Relationships

- [Channel Base Interface](Channel_Base_Interface.md) (3 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (2 shared connections)

## Source Files

- `aios/channels/email_.py`

## Audit Trail

- EXTRACTED: 15 (83%)
- INFERRED: 3 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*