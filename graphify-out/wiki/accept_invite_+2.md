# accept_invite() +2

> 6 nodes · cohesion 0.47

## Key Concepts

- **Invitation** (11 connections) — `aios/db/models.py`
- **accept_invite()** (9 connections) — `aios/dashboard/app.py`
- **TestInviteEmailMatch** (4 connections) — `tests/test_security.py`
- **.test_accept_invite_wrong_email_rejected()** (4 connections) — `tests/test_security.py`
- **Accept invite link from email.** (1 connections) — `aios/dashboard/app.py`
- **Invite acceptance must require matching email and deny superadmin.** (1 connections) — `tests/test_security.py`

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (8 shared connections)
- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (3 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (3 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (1 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)

## Source Files

- `aios/dashboard/app.py`
- `aios/db/models.py`
- `tests/test_security.py`

## Audit Trail

- EXTRACTED: 17 (74%)
- INFERRED: 6 (26%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*