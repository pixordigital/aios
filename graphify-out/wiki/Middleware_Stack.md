# Middleware Stack

> 15 nodes · cohesion 0.20

## Key Concepts

- **Request** (9 connections)
- **middleware** (8 connections)
- **dashboard_csrf()** (6 connections) — `aios/main.py`
- **rls_middleware()** (5 connections) — `aios/main.py`
- **dashboard_auth()** (4 connections) — `aios/main.py`
- **limit_body_size()** (4 connections) — `aios/main.py`
- **rate_limit_handler()** (4 connections) — `aios/main.py`
- **request_logging()** (4 connections) — `aios/main.py`
- **trace_middleware()** (4 connections) — `aios/main.py`
- **add_request_id()** (3 connections) — `aios/main.py`
- **security_headers()** (3 connections) — `aios/main.py`
- **Reject dashboard state-changing requests from external origins.** (1 connections) — `aios/main.py`
- **Log every request with method, path, status, duration.** (1 connections) — `aios/main.py`
- **exception_handler** (1 connections)
- **RateLimitExceeded** (1 connections)

## Relationships

- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (9 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (2 shared connections)
- [RFC7807 Error Model](RFC7807_Error_Model.md) (2 shared connections)
- [File Upload & AV Scanning](File_Upload_&_AV_Scanning.md) (1 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (1 shared connections)
- [Structured Output & Traces](Structured_Output_&_Traces.md) (1 shared connections)

## Source Files

- `aios/main.py`

## Audit Trail

- EXTRACTED: 35 (95%)
- INFERRED: 2 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*