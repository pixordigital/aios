---
name: api-contract
description: Design versioned, idempotent, traceable HTTP APIs. Use when creating endpoints, envelopes, errors, or integration contracts between services (AIOS↔ARVO style).
---

# API Contract

Contract small, version early, break never.

## Rules

- **Prefix**: `/api/.../v1/...` (version in path). Already: `aios/integrations/arvo/v1`, `arvo/app/integrations/aios/v1`.
- **Envelope**: `{type, payload, business_trace_id, event_version, occurred_at}`. Trace threaded end-to-end (spec §10).
- **Idempotency**: `Idempotency-Key` header required on POST side-effects. In-memory fast + DB persist survive restart (`IntegrationEvent`). Return `deduplicated: true` on replay.
- **Auth**: HMAC service auth (`X-Service-Key-Id/Timestamp/Nonce/Signature`, 300s skew, nonce dedup). Never reuse user JWT for service→service.
- **Errors**: `{error, code, details}` with correct status: 400 validation, 401 auth, 404 not found, 409 conflict, 429 retryable, 5xx retryable. Don't leak internals.
- **Validation**: Pydantic `Field(max_length, pattern)`. `business_trace_id` regex `^[a-zA-Z0-9_-]+$`.

## Checklist per endpoint

- [ ] Pydantic model with `max_length` + `pattern` where regex needed
- [ ] `Idempotency-Key` if writes
- [ ] HMAC verify + nonce persist (DB) + timestamp skew check
- [ ] Trace echo in response
- [ ] `TestClient` happy + auth-fail + replay + idempotency tests

## Reuse in this repo

- `aios/integrations/arvo/auth.py:sign_request/verify_request`
- `aios/integrations/arvo/routes.py:ArvoEvent/ContextRequest`
- `aios/integrations/arvo/client.py:send_event/ping` (retry 3×, 5s timeout, backoff)

## Don't

- New envelope format — reuse existing `AiosEvent`/`ArvoEvent`.
- Bearer for service auth, new dep for HMAC (stdlib `hmac`+`hashlib` enough).
