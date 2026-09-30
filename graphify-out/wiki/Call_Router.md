# Call Router

> 15 nodes · cohesion 0.24

## Key Concepts

- **voice/__init__.py** (10 connections) — `aios/core/whatsapp/voice/__init__.py`
- **call_router.py** (9 connections) — `aios/core/whatsapp/voice/call_router.py`
- **webrtc_handler.py** (8 connections) — `aios/core/whatsapp/voice/webrtc_handler.py`
- **ivr_engine.py** (7 connections) — `aios/core/whatsapp/voice/ivr_engine.py`
- **start_outbound()** (5 connections) — `aios/core/whatsapp/voice/call_router.py`
- **IVRFlow** (4 connections) — `aios/core/whatsapp/voice/ivr_engine.py`
- **webrtc_create_session()** (4 connections) — `aios/core/whatsapp/voice/webrtc_handler.py`
- **route_inbound()** (3 connections) — `aios/core/whatsapp/voice/call_router.py`
- **render_prompt()** (3 connections) — `aios/core/whatsapp/voice/ivr_engine.py`
- **synthesize_ivr()** (3 connections) — `aios/core/whatsapp/voice/ivr_engine.py`
- **.add_greet()** (2 connections) — `aios/core/whatsapp/voice/ivr_engine.py`
- **IVRNode** (2 connections) — `aios/core/whatsapp/voice/ivr_engine.py`
- **webrtc_attach_plugin()** (2 connections) — `aios/core/whatsapp/voice/webrtc_handler.py`
- **WhatsApp Voice Phase B — Janus WebRTC + Kokoro + IVR (WhatsApp+WebRTC only).** (1 connections) — `aios/core/whatsapp/voice/__init__.py`
- **Renderiza via Kokoro (aios/core/voice).** (1 connections) — `aios/core/whatsapp/voice/ivr_engine.py`

## Relationships

- [IVR, PII Redaction & Call Routing](IVR,_PII_Redaction_&_Call_Routing.md) (5 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (4 shared connections)
- [WhatsApp Gateway API](WhatsApp_Gateway_API.md) (2 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (1 shared connections)
- [whatsapp/config.py +2](whatsapp-config.py_+2.md) (1 shared connections)

## Source Files

- `aios/core/whatsapp/voice/__init__.py`
- `aios/core/whatsapp/voice/call_router.py`
- `aios/core/whatsapp/voice/ivr_engine.py`
- `aios/core/whatsapp/voice/webrtc_handler.py`

## Audit Trail

- EXTRACTED: 39 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*