# AIOS Operating Model — implemented foundations

Derived from the 21 Nov 2026 consolidated context brief. This records what is
now enforced in code versus what remains a proposal or needs external input.

## Implemented (deterministic, tested)

| Brief area | Module | Enforced |
|---|---|---|
| §5 OCP | `aios/governance/ocp.py` | Departments, human/agent membership, authority grants, shared task registry, goals, decision records, org events; closed task lifecycle; grant validity/revocation/scope; 12-field Founder protocol; Founder-only approval for levels 2–3 |
| §15 Privacy/LGPD | `aios/governance/privacy.py` | Processing-activity registry, data-subject requests, allow/deny/approval/restrict/defer evaluation, fail-closed policy, purpose binding, opt-out, legal hold, retention |
| §16 AI SOC | `aios/governance/security.py` | Incidents, telemetry, autonomous/conditional/human response authority, severity classification, Privacy handoff, MTTD/MTTC metrics |
| §17 Model strategy | `aios/governance/model_intelligence.py`, `aios/api/model_intelligence.py` | Model registry, eligibility filters, cost-per-success selection, evidence-backed proposals, approved-only rollback; Founder-gated tenant `/api/models` registry/select/recommend/rollback |
| §12 Solution fit | `aios/governance/capability_registry.py`, `aios/api/capabilities.py` | Capability maturity registry, solution-fit dispositions, pipeline stage order; tenant-scoped `/api/capabilities` create/list/evaluate/assessments |
| §11 Lean Startup | `aios/governance/innovation.py`, `aios/api/innovation.py` | Hypotheses, declared experiments with thresholds/stop conditions, deterministic evaluate, Founder-only pivot/persevere decisions, scoreboard; tenant-scoped `/api/innovation` |
| §13 CRM | `aios/core/crm_intelligence.py` | Accounts, contacts, unified interaction timeline, relationship health, deterministic prioritisation |
| §12 LIA | `aios/core/lia.py`, `aios/api/lia.py` | Sources, signals, campaigns, members, outreach, suppression; fail-closed contact gate; Founder campaign approval; tenant-scoped `/api/lia` with CRM handoff |
| §14 Knowledge | `aios/governance/knowledge.py`, `aios/api/knowledge.py` | Provenance-tagged records, tenant/dept/classification-aware retrieval, fact promotion guard, Founder soft-delete; `/api/knowledge/records` |
| §4 ICM-X hardening | `aios/icm/enforcement.py` | Per-stage call/cost budget, tool gate, retry classification, idempotency keys; adapter records spend in provenance; AgentRuntime enforces stage budget before each LLM call |
| §19 Slack | `aios/governance/slack_taxonomy.py`, `aios/api/slack.py` | Read-only `/api/slack` taxonomy/system-of-record/migration gate; no agent channels, no channel mutation routes |
| §5 API | `aios/api/ocp.py`, `aios/api/privacy.py`, `aios/api/security.py`, `aios/api/capabilities.py`, `aios/api/innovation.py`, `aios/api/lia.py`, `aios/api/knowledge.py`, `aios/api/slack.py`, `aios/api/model_intelligence.py` | `/api/ocp/*` task/decision/execute; `/api/privacy/*` registry/evaluate/requests; `/api/security/*` incidents/respond/close; `/api/capabilities/*` registry/solution-fit; `/api/innovation/*` experiments/decisions; `/api/lia/*` acquisition; `/api/knowledge/records` governance; `/api/slack/*` read-only taxonomy/gate; `/api/models/*` registry/select/recommend/rollback |

Migrations: `alembic/versions/o7p8q9r0s1t2` … `w5x6y7z8a9b0`.

## Deliberately not automated

- Department membership and authority are data; they do not grant permissions by themselves.
- `Encarregado` and legal clearance remain human responsibilities.
- Jev is not integrated; no evidence yet that it beats deterministic rules.
- Predictive conversion forecasting waits for real outcome data.
- Track C (autonomous managers, cross-department optimisation) waits for evidence.

## Blocked / needs external input

1. **Slack connection and workspace inspection.** No credentials and no connected
   integration in this environment. Do not create or rename channels until the
   real inventory and migration map are approved.
2. **Legal review.** Privacy registry entries and legitimate-interest assessments
   need qualified Brazilian privacy counsel.
3. **Customer pilot.** Dealership workflow needs an authorised customer, data and
   success criteria.

## Phase completion check (21 Nov 2026 brief, section by section)

| Brief section | Status now |
|---|---|
| 1 Executive summary | Implemented direction (Python/FastAPI/Jinja2, deterministic-first, OCP, BYOK, LGPD, Lean) codified in docs. |
| 2-3 Business/technical direction | Done: direction codified; capability registry API records actual maturity/limits/commercial availability (`/api/capabilities`); production infra confirmed Hetzner CX33/Coolify (founder-stated 2026-11-22). |
| 4 ICM-X hardening | Done in code (`aios/icm/enforcement.py`, adapter budget, agent tool charge). Runtime wiring verified by tests. |
| 5 OCP | Done: models, rules, API, decision→task execution. |
| 6 Departments | Done (code/activation primitive): `POST /api/ocp/departments/bootstrap-defaults` (Founder-only, idempotent) seeds 8 lean §6 defaults: Executive/Secretary, Commercial, Operations, Engineering, Governance, Product, Security/AI SOC, Privacy & LGPD. No agent workforce auto-created. Org-specific ownership/memberships remain Founder decisions. |
| 7 Founder authority | Done: deterministic level mapping + 12-field protocol + Founder-only approval. |
| 8 Skills | Done: deterministic lifecycle state machine + persisted `skills.status` + Founder-gated API transition; publish/deprecate require Founder. |
| 9 Process intelligence | Done: deterministic conformance checks wired into workflow runs (`_process_conformance` output); task lifecycle deterministic. |
| 10 Performance | SQL/Python authoritative KPI calculations (`aios/governance/kpi.py`) + tenant-scoped CRM KPI API (`GET /api/analytics/kpi/sales`); deterministic interpretation over supplied baseline; no invented targets. |
| 11 Lean Startup | Done: hypotheses/experiments/scoreboard + tenant-scoped API with declared-field gate, deterministic evaluation and Founder-only decisions. |
| 12 LIA | Done: tenant-scoped API over sources/campaigns/suppression/members; fail-closed contact gate and deterministic LIA→CRM handoff; actual outreach execution still external. |
| 13 CRM/customer intelligence | Done: accounts/contacts/timeline/health implemented. |
| 14 Knowledge/Secretary | Done: provenance-tagged records + permission-aware API retrieval, promotion gate and Founder soft-delete; Secretary meeting intelligence still external. |
| 15 Privacy/LGPD | Done: registry + enforcement + API implemented; legal review still external. |
| 16 Security/AI SOC | Done: incidents/response/metrics implemented; API added. |
| 17 Model strategy | Done: registry/optimizer/provider usage attribution/workflow-node cost charge/provider health/cost anomaly detection/Jev harness; Jev adoption needs controlled-eval evidence. |
| 18 Product/engineering priorities | Partial: foundations implemented; commercial pilot pending (see §21 sequence). |
| 19 Slack restructuring | Proposal + read-only inventory done (Pixor workspace, 7 public/0 private channels, 3 users; draft `docs/SLACK_MIGRATION_DRAFT.md`). Structural changes blocked: Founder-approved per-channel migration map + explicit per-batch confirmation; AIOS gate still requires inventoried+approved+Founder metadata. |
| 20-21 Decision paths, immediate sequence | Foundations → governance → pilot-ready loop; §21-8 Lean experiments loop now API-backed (`/api/innovation`). |

## Commercial pilot status

- Narrow pilot proposed: dealership lead operations (intake, qualification, CRM update, follow-up, human escalation, outcome measurement).
- Not executed: needs authorised pilot customer, baseline data, success criteria and founder sign-off.
- Preconditions now in place: LIA contact gate, CRM accounts/contacts/timeline, decision→task execution, OCP tasks, privacy gate, security response.

## Phase completion check — remaining areas

- Skills lifecycle (Draft→Under review→Testing→Approved→Published) enforcement: deterministic state machine with Founder gates; persisted `skills.status` and `POST /api/skills/{id}/transition` enforce the ladder.
- Process conformance supervision (skipped steps, wrong tools, missing approvals, invalid outputs, exceeded limits, un-escalated exceptions): deterministic checks wired into workflow execution; findings in `_process_conformance` run output (`aios/governance/process_conformance.py`).
- Performance authoritative KPI calculations (SQL/Python, not LLM): implemented as deterministic Python functions; deterministic narrative interpretation added.
- Jev controlled evaluation (Python-only vs Jev vs hybrid): harness implemented; adoption open (needs controlled decision dataset and founder decision).
- Provider cost integration: adapters return input/output/cached usage; agent + workflow runtime record actual tokens/cost; provider health checks and median-based spend anomaly detection implemented.

## Commercial pilot

- Status: not executed. Requires authorised customer, baseline metrics, legal basis and founder sign-off.
- Blocked by user input: customer authorisation and pilot scope approval.

## Open hard external dependencies

- Slack connection credentials + real workspace inspection.
- Qualified Brazilian privacy counsel for LGPD assessments.
- Founder decisions for material OCP/privacy/security changes.
