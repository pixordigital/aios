# SDK Conversations API

> 16 nodes · cohesion 0.14

## Key Concepts

- **ConversationHandle** (12 connections) — `aios/sdk/conversation.py`
- **ConversationsAPI** (8 connections) — `aios/sdk/client.py`
- **.conversations()** (2 connections) — `aios/sdk/client.py`
- **.create()** (2 connections) — `aios/sdk/client.py`
- **.get()** (2 connections) — `aios/sdk/client.py`
- **.__init__()** (2 connections) — `aios/sdk/client.py`
- **.messages()** (2 connections) — `aios/sdk/conversation.py`
- **.send()** (2 connections) — `aios/sdk/conversation.py`
- **.upload_file()** (2 connections) — `aios/sdk/conversation.py`
- **.list()** (1 connections) — `aios/sdk/client.py`
- **.__init__()** (1 connections) — `aios/sdk/conversation.py`
- **.__repr__()** (1 connections) — `aios/sdk/conversation.py`
- **Send a message and return the agent's reply.** (1 connections) — `aios/sdk/conversation.py`
- **Get conversation history.** (1 connections) — `aios/sdk/conversation.py`
- **Upload a file to this conversation.** (1 connections) — `aios/sdk/conversation.py`
- **A conversation with an agent — send messages, get replies.** (1 connections) — `aios/sdk/conversation.py`

## Relationships

- [sdk/agent.py +2](sdk-agent.py_+2.md) (4 shared connections)
- [AIOS SDK Client](AIOS_SDK_Client.md) (2 shared connections)
- [SDK Teams API](SDK_Teams_API.md) (1 shared connections)

## Source Files

- `aios/sdk/client.py`
- `aios/sdk/conversation.py`

## Audit Trail

- EXTRACTED: 23 (96%)
- INFERRED: 1 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*