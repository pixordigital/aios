# Auth Token Factory

> 82 nodes · cohesion 0.05

## Key Concepts

- **api/auth.py** (75 connections) — `aios/api/auth.py`
- **get_dashboard_user()** (20 connections) — `aios/api/deps.py`
- **register()** (17 connections) — `aios/api/auth.py`
- **_oauth_login_or_register()** (13 connections) — `aios/api/auth.py`
- **login()** (12 connections) — `aios/api/auth.py`
- **Request** (10 connections)
- **forgot_password()** (9 connections) — `aios/api/auth.py`
- **google_calendar_disconnect()** (9 connections) — `aios/api/auth.py`
- **post** (9 connections)
- **refresh_token()** (9 connections) — `aios/api/auth.py`
- **reset_password()** (9 connections) — `aios/api/auth.py`
- **_verify_jwt_token()** (9 connections) — `aios/api/auth.py`
- **_create_jwt_token()** (8 connections) — `aios/api/auth.py`
- **google_calendar_login()** (8 connections) — `aios/api/auth.py`
- **_load_ed25519_keys()** (8 connections) — `aios/api/auth.py`
- **google_calendar_callback()** (7 connections) — `aios/api/auth.py`
- **_create_access_token()** (6 connections) — `aios/api/auth.py`
- **_create_refresh_token()** (6 connections) — `aios/api/auth.py`
- **github_callback()** (6 connections) — `aios/api/auth.py`
- **google_callback()** (6 connections) — `aios/api/auth.py`
- **_oauth_pop()** (6 connections) — `aios/api/auth.py`
- **totp_backup_codes()** (6 connections) — `aios/api/auth.py`
- **totp_verify()** (6 connections) — `aios/api/auth.py`
- **verify_email()** (6 connections) — `aios/api/auth.py`
- **_create_email_token()** (5 connections) — `aios/api/auth.py`
- *... and 57 more nodes in this community*

## Relationships

- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (23 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (17 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (16 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (14 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (7 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (5 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (4 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (3 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (3 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (2 shared connections)
- [Middleware Stack](Middleware_Stack.md) (2 shared connections)

## Source Files

- `aios/api/auth.py`
- `aios/api/deps.py`

## Audit Trail

- EXTRACTED: 224 (86%)
- INFERRED: 37 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*