# Business OS — Sandbox / Live-Safe Setup

> **Scaffold / live-safe slice, not live business automation.** Configure only components with real credentials and explicit human approval. Any external side effect requires HITL. Keep shadow mode enabled until a human owner validates end-to-end behavior.

## Safety defaults (required)

- **HITL required:** every external side effect (send, book, reschedule, cancel, publish, state change) needs explicit human-in-the-loop approval before execution. Do not bypass approval gates.
- **Shadow mode:** run the slice in shadow mode first. Observe proposed actions, payloads, and audit logs; do not let agents perform real external actions without review.
- **Secrets as placeholders:** use env vars / secret manager. Never commit real credentials. Values below are placeholders only.
- **Fail closed:** missing config, missing approval, or missing idempotency key must deny the action.
- **Human owner:** a named human owner approves go-live, credentials, recipients, and any irreversible action.

## 1) Cal.com first (self-hosted scheduling)

Cal.com is the first live-safe integration slice. Configure self-hosted Cal.com before enabling booking actions.

| Placeholder env var | Purpose | Notes |
|---|---|---|
| `CALCOM_BASE_URL` | Cal.com API base URL | Example placeholder: `https://cal.example.com` or internal service URL. Repo config also uses `AIOS_CALCOM_API_URL`. |
| `CALCOM_API_KEY` | Cal.com API key | Create in Cal.com Settings > Security. Repo config also uses `AIOS_CALCOM_API_KEY`. |
| `CALCOM_EVENT_TYPE` | Default event type | Event type id/slug used for bookings. Repo config also uses `AIOS_CALCOM_EVENT_TYPE_ID`. |
| `CALCOM_WEBHOOK_SECRET` | Webhook signature secret | Verify inbound Cal.com webhooks. Keep secret in env/secret manager. |

Setup checklist:

- [ ] Deploy/reach self-hosted Cal.com and confirm admin access.
- [ ] Create event type and availability; capture `CALCOM_EVENT_TYPE`.
- [ ] Generate API key; set `CALCOM_API_KEY`.
- [ ] Set `CALCOM_BASE_URL` to the reachable Cal.com API/UI base.
- [ ] Configure webhook secret as `CALCOM_WEBHOOK_SECRET`; verify signature checks.
- [ ] Keep HITL required for booking changes (create/reschedule/cancel).
- [ ] Test in shadow mode/sandbox with injected or test client before any real booking.

## 2) CRM internal (no external creds)

- Use the internal CRM/data model only for the live-safe slice.
- **No external CRM credentials**: do not configure HubSpot/Salesforce/Pipedrive or similar external CRM creds in this slice.
- Customer/contact data stays in AIOS-controlled storage with access control and audit.
- Human owner reviews field mapping, data ownership, and LGPD/privacy constraints before any outbound use.

## 3) Resend (email)

| Placeholder env var | Purpose | Notes |
|---|---|---|
| `RESEND_API_KEY` | Resend API key | Secret; store in env/secret manager. |
| `RESEND_FROM` | Sender email/from address | Must be on a verified domain. Adapter also accepts `from` config key. |

Setup checklist:

- [ ] Create Resend API key; set `RESEND_API_KEY` placeholder in secret manager.
- [ ] Verify sending domain in Resend (SPF/DKIM/DMARC/domain verification complete).
- [ ] Set `RESEND_FROM` to a verified sender address.
- [ ] Keep HITL required for external sends; no send without explicit approval.
- [ ] Test with sandbox/shadow mode and approved test recipient before production.

## 4) Evolution (WhatsApp)

| Placeholder env var | Purpose | Notes |
|---|---|---|
| `EVOLUTION_SERVER_URL` | Evolution API base URL | Example placeholder: `http://evolution:8080` (internal) or approved HTTPS endpoint. |
| `EVOLUTION_API_KEY` | Evolution API key | Secret; rotate per policy. |
| `EVOLUTION_INSTANCE` | WhatsApp instance name/id | Use the configured instance for the sandbox slice; confirm connection state before tests. |

Setup checklist:

- [ ] Set `EVOLUTION_SERVER_URL` and `EVOLUTION_API_KEY` in env/secret manager.
- [ ] Select/create `EVOLUTION_INSTANCE`; verify instance status and webhook configuration.
- [ ] Keep HITL required for outbound WhatsApp messages.
- [ ] Validate opt-in/privacy and message template/compliance constraints with human owner.
- [ ] Run shadow mode/sandbox tests before enabling any real recipient send.

## Go-live gate

Do not treat this slice as live business automation until:

- [ ] Credentials configured and validated in secret manager.
- [ ] HITL approval path tested for every external side effect.
- [ ] Shadow mode observations reviewed by human owner.
- [ ] Audit logs capture who/when/what/result for actions.
- [ ] Rollback/kill-switch path documented and tested.
- [ ] Owner signs off with evidence; missing evidence means `not_configured`/not live.
