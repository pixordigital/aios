# Secrets Encryption

> 31 nodes · cohesion 0.10

## Key Concepts

- **Credential** (22 connections) — `aios/db/models.py`
- **decrypt_secret()** (15 connections) — `aios/core/secrets.py`
- **encrypt_secret()** (15 connections) — `aios/core/secrets.py`
- **core/secrets.py** (13 connections) — `aios/core/secrets.py`
- **http_request.py** (13 connections) — `aios/tools/http_request.py`
- **decrypt_channel_config()** (12 connections) — `aios/core/secrets.py`
- **hubspot.py** (8 connections) — `aios/tools/hubspot.py`
- **pipedrive.py** (8 connections) — `aios/tools/pipedrive.py`
- **rdstation.py** (8 connections) — `aios/tools/rdstation.py`
- **put_secret()** (5 connections) — `aios/api/secrets.py`
- **set_org_secret()** (4 connections) — `aios/core/secrets.py`
- **HttpRequestTool** (4 connections) — `aios/tools/http_request.py`
- **_is_private()** (4 connections) — `aios/tools/http_request.py`
- **HubSpotTool** (4 connections) — `aios/tools/hubspot.py`
- **PipedriveTool** (4 connections) — `aios/tools/pipedrive.py`
- **RDStationTool** (4 connections) — `aios/tools/rdstation.py`
- **_key()** (3 connections) — `aios/core/secrets.py`
- **.run()** (3 connections) — `aios/tools/http_request.py`
- **get_org_secrets()** (2 connections) — `aios/core/secrets.py`
- **HttpRequestInput** (2 connections) — `aios/tools/http_request.py`
- **HubSpotInput** (2 connections) — `aios/tools/hubspot.py`
- **.run()** (2 connections) — `aios/tools/hubspot.py`
- **PipedriveInput** (2 connections) — `aios/tools/pipedrive.py`
- **.run()** (2 connections) — `aios/tools/pipedrive.py`
- **RDStationInput** (2 connections) — `aios/tools/rdstation.py`
- *... and 6 more nodes in this community*

## Relationships

- [Tool Base Abstraction](Tool_Base_Abstraction.md) (22 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (10 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (8 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (4 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (4 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (3 shared connections)
- [CRM2 API](CRM2_API.md) (2 shared connections)
- [Voice API & Call Placement](Voice_API_&_Call_Placement.md) (2 shared connections)
- [Channel Base Interface](Channel_Base_Interface.md) (2 shared connections)
- [CRM2 Routes](CRM2_Routes.md) (2 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)

## Source Files

- `aios/api/secrets.py`
- `aios/core/secrets.py`
- `aios/db/models.py`
- `aios/tools/http_request.py`
- `aios/tools/hubspot.py`
- `aios/tools/pipedrive.py`
- `aios/tools/rdstation.py`

## Audit Trail

- EXTRACTED: 103 (84%)
- INFERRED: 19 (16%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*