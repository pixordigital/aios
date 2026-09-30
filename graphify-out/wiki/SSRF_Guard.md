# SSRF Guard

> 19 nodes · cohesion 0.17

## Key Concepts

- **check_url()** (14 connections) — `aios/tools/ssrf.py`
- **test_ssrf_guard.py** (13 connections) — `tests/test_ssrf_guard.py`
- **ssrf.py** (9 connections) — `aios/tools/ssrf.py`
- **is_private_host()** (6 connections) — `aios/tools/ssrf.py`
- **urllib_parse** (4 connections)
- **test_fails_closed_on_unresolvable_host()** (3 connections) — `tests/test_ssrf_guard.py`
- **test_internal_targets_blocked()** (3 connections) — `tests/test_ssrf_guard.py`
- **test_non_http_schemes_blocked()** (3 connections) — `tests/test_ssrf_guard.py`
- **parametrize** (2 connections)
- **test_allow_private_override()** (2 connections) — `tests/test_ssrf_guard.py`
- **test_no_hostname()** (2 connections) — `tests/test_ssrf_guard.py`
- **test_public_url_allowed()** (2 connections) — `tests/test_ssrf_guard.py`
- **SSRF guard for tools that fetch user- or agent-supplied URLs. Shared by…** (1 connections) — `aios/tools/ssrf.py`
- **True when host resolves to a private/internal address. Fails closed.** (1 connections) — `aios/tools/ssrf.py`
- **Return an error string if the URL must not be fetched, else None.** (1 connections) — `aios/tools/ssrf.py`
- **socket** (1 connections)
- **SSRF guard tests. Regression: etl_url had no SSRF protection at all — it…** (1 connections) — `tests/test_ssrf_guard.py`
- **test_etl_url_imports_guard()** (1 connections) — `tests/test_ssrf_guard.py`
- **test_http_get_uses_shared_guard()** (1 connections) — `tests/test_ssrf_guard.py`

## Relationships

- [Tool Base Abstraction](Tool_Base_Abstraction.md) (4 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (2 shared connections)
- [Anti-Ban Proxy & Fingerprint](Anti-Ban_Proxy_&_Fingerprint.md) (1 shared connections)
- [Semantic Search & Embeddings](Semantic_Search_&_Embeddings.md) (1 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (1 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (1 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (1 shared connections)

## Source Files

- `aios/tools/ssrf.py`
- `tests/test_ssrf_guard.py`

## Audit Trail

- EXTRACTED: 41 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*