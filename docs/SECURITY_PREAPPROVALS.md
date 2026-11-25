# Security Preapprovals API

Minimal contract for governed response preapprovals. Founder UI is read-only at `/dashboard/security/preapprovals`; writes via API/config only. Full approval workflow not implemented.

## Authz

- All `/api/security/preapprovals*` endpoints require authenticated user.
- Founder/owner authority required (`is_founder_authority`). Non-founder: `403`.
- Denied checks emit `security.authz.denied` event with `reason=founder_required`, source per endpoint.

## Storage

- Stored in `org.extra_data.security_policy`.
- Shared app DB storage only; **no independent/append-only sink**.
- Shape:
  - `preapproved_actions: string[]` - action names from `RESPONSE_AUTHORITY`.
  - `approvals: object[]` - records like `{id?, action, approved, ticket?, note?}`.
  - metadata on save: `updated_at`, `updated_by`.

## Endpoints

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/security/preapprovals` | Return `{preapproved_actions, approvals, storage}` |
| PUT | `/api/security/preapprovals` | Replace provided fields; validates action names and shapes |
| POST | `/api/security/preapprovals/actions` | Add action idempotently; body `{action}` |
| DELETE | `/api/security/preapprovals/actions/{action}` | Remove action; unknown action name `400` |
| POST | `/api/security/preapprovals/approvals` | Add/replace approval record by `id`; body is approval object |
| DELETE | `/api/security/preapprovals/approvals/{approval_id}` | Remove by id; missing `404` |

## Validation / errors

- `400`: missing/invalid shape, unknown action, empty action.
- `403`: founder required.
- `404`: org missing on mutating endpoints where checked; approval id missing on delete.
- Unknown action checked against `RESPONSE_AUTHORITY`.

## Audit

- Mutations record `security.policy.preapprovals_updated` with `before/after` payload.
- Respond gateway uses stored preapprovals; decision includes `preapproval_source`.

## Tests

- `tests/test_security_api.py` covers CRUD, founder 403, validation edges, 404, respond authorization.
