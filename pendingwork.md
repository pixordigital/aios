## pending work handoff

### AIOS consolidated brief — governance/OCP foundations (2026-11-22)

Implemented deterministic foundations from `/tmp/a383f41d-...pdf`:
`aios/governance/{ocp,privacy,security,model_intelligence,capability_registry,innovation,knowledge,slack_taxonomy}.py`,
`aios/core/{crm_intelligence,lia}.py`, `aios/icm/enforcement.py`; models registered in
`aios/db/models.py`; migrations `o7p8q9r0s1t2`..`w5x6y7z8a9b0`; docs `docs/AIOS_OPERATING_MODEL.md`;
tests `tests/test_{ocp,privacy_governance,security_operations,model_intelligence,capability_registry,innovation_learning,crm_intelligence,lia,knowledge_access,icm_enforcement,slack_taxonomy}.py`.

Open items:
- [ ] Slack structural migration (BLOCKED: Founder decision/approval). Credentials present in gitignored `.env`; read-only inventory complete (`docs/SLACK_MIGRATION_DRAFT.md`, 7 public/0 private, 3 users). Need Founder-approved per-channel map + explicit per-batch confirmation before any create/rename/archive; set AIOS migration-gate metadata only via approved process.
- [x] OCP API surface `/api/ocp/{departments,tasks,decisions}` (`aios/api/ocp.py`, tests `tests/test_ocp_api.py`);
- [x] Privacy + Security API routers added (`aios/api/privacy.py`, `aios/api/security.py`, mounted in `aios/api/router.py`).
- [x] ICM agent runtime now enforces `AgentRuntime._icm_budget` (stage ceilings) before LLM calls (`aios/core/agent.py`).
- [x] Decision→task execution linkage added: `execute_decision` (`aios/governance/ocp.py`) + `POST /api/ocp/decisions/{id}/execute` (`aios/api/ocp.py`).
- [x] ICM agent tool loop now charges `StageBudget.charge_tool()` per executed tool (ceiling enforced, budget exceeded yields STREAM_ERROR).
- [x] Task-level budget check added (`task_budget_check` in `aios/governance/ocp.py`); LLM call cost now charged via `estimate_cost` in agent runtime (stream + structured).
- [x] Provider cost attribution: adapters return input/output/cached usage; runtime records actual tokens/cost (`aios/core/providers.py`, `aios/core/agent.py`). Verified 100 tests + inline usage checks.
- [x] Fixed unbound fallback budget (`max_cost_usd=inf`); `0.0` blocked all non-stage agents (9 router regressions now pass).
- [x] Provider health checks (`LLMProvider.health_check`, `provider_health`) + deterministic cost anomaly detection (`detect_cost_anomalies`); 53 tests + inline checks pass.
- [x] Workflow-node cost attribution: `aios/core/workflow.py` pre-checks stage call ceiling, charges real runtime cost + reflection estimates into adapter budget; run cost read from stage provenance. Tests `tests/test_workflow_cost_attribution.py` (64-test workflow/ICM batch pass).
- [x] LIA→CRM handoff decision (`crm_handoff_decision` in `aios/core/lia.py`) + tests; inherits contact gate.
- [x] Deterministic KPI interpretation over caller baseline (`interpret_kpis` in `aios/governance/kpi.py`) + tests; no invented targets.
- [x] Workflow-run process conformance (`_process_conformance` output) + tests (`tests/test_workflow_process_conformance.py`).
- [x] Capability registry + Solution-Fit API: `aios/api/capabilities.py` mounted at `/api/capabilities` (tenant-scoped create/list/evaluate/assessments); tests `tests/test_capability_api.py` (51-test batch pass).
- [x] Lean innovation API: `aios/api/innovation.py` mounted at `/api/innovation` (declared-field gate, deterministic evaluate, Founder-only decide, scoreboard); tests `tests/test_innovation_api.py` (47-test batch pass).
- [x] LIA API: `aios/api/lia.py` mounted at `/api/lia` (sources/campaigns/suppression/members, Founder approval, fail-closed contact check, CRM handoff); tests `tests/test_lia_api.py`.
- [x] Knowledge governance API: `aios/api/knowledge.py` extended with `/api/knowledge/records` (provenance gate, permission-aware listing, promotion, Founder soft-delete, retention eligibility); tests `tests/test_knowledge_governance_api.py` (50-test batch pass).
- [x] Slack taxonomy read-only API: `aios/api/slack.py` mounted at `/api/slack` (taxonomy, system-of-record, migration gate, channel validation; no mutation routes); tests `tests/test_slack_api.py`.
- [x] Model Intelligence API: `aios/api/model_intelligence.py` mounted at `/api/models` (registry, Founder approval, fail-closed eligibility/select, recommend, rollback target); tests `tests/test_model_intelligence_api.py` (50-test batch pass).
- [x] KPI API: `GET /api/analytics/kpi/sales` in `aios/api/analytics.py` (authoritative CRM SQL/Python metrics, pipeline/baseline filter, deterministic interpretation); tests `tests/test_analytics_kpi.py` (7-test batch pass).
- [x] `docs/AIOS_OPERATING_MODEL.md` phase rows refreshed (§12, §10, §17, remaining areas).
- [x] Skills lifecycle persistence: `skills.status` column + migration `b8c9d0e1f2a3` + Founder-gated `POST /api/skills/{id}/transition` + tests (`tests/test_skills_lifecycle_api.py`).
- [ ] Legal review of privacy registry / legitimate-interest entries (human/counsel).
- [ ] Dealership pilot with authorised customer data and baseline metrics.

### ICM-X full architecture rollout (phased) - COMPLETE ✓

1. Persistence/recovery: stage attempts stored in `WorkflowRun.outputs` (`_icm_stage_attempts`), idempotent resume via `resume_outputs`/`resume_status` — test added (`tests/test_workflow_resume_icm.py`) and passes.
2. Approvals: `bind_approval()` wired into both workflow stage execution paths, approval ID + fingerprint recorded in attempt dict.
3. Selective reruns: `invalidate_dependents()` transitive-dependency resolver + test (`tests/test_icm_checkpoint.py`).
4. Benchmarking: `record_run_metrics()` cost/latency/tokens per run in `_persist` output column.
5. Versioned workspace completion: `data/tenants/default/workspaces/b2b_lead_research` with L0-L3 stages + stage manifests (company_research, lead_qualification) already seeded with version 1.0.0.
6. Final: run full ICM/workflow suite and document rollout — 25 tests pass (24 existing + 1 new resume-idempotency integration test).

**All phases complete.** No further DB/schema changes needed; package is inert until explicitly called per architectural boundary docs.

### AIOS homepage nav — RESOLVED ✓ (2026-11-21, verified live)

- Root causes:
  1. Hamburger invisible on mobile: `.nav-burger { display: none }` had no `@media` override; no JS toggle/open state existed.
  2. Desktop pill broken: `nav` lost explicit width (commit `a0aa949` dropped it); only `max-width: 1200px` + `left:50%/translateX` → shrink-to-fit, pill renders wrong on big screens.
- Fixes in `website/index.html`:
  - `nav { width: min(1200px, calc(100vw - 32px)); }` restored (commit `ccd2f79`).
  - `.nav-burger { display: flex }` under `@media (max-width: 768px)`; `nav.open .links` full-width column panel; `.nav-burger.open` X animation; JS toggle (click burger → `nav.open`; click link → closes) — commit `cf4d0cd`.
  - Orphaned mobile CSS given `@media (max-width: 768px)` wrapper (`ab910ec`); `max-width: 100vw`→`100%` (`83b4664`); grid `min-width: 0` (`bdc73e7`).
- Live deploy: Coolify app `38908ddf-a875-4105-a93f-a4570513911f`, deploy `eu4uriwxlzsayukqeltbg7dt` (commit `ccd2f79`) finished 2026-11-21 ~11:55.
- Verified live (agent-browser):
  - 1440×900 & 1920×1080: nav width 1200px, radius 999px, links visible, burger hidden, no horizontal overflow.
  - 375×667 & 320×568: burger `display:flex`, nav width 343px / 288px, tap opens menu (`flex-direction: column`, full-width, below pill), link tap closes menu, no overflow.
- Follow-up fixes (commits `779cccb`, `3f694bc`, `dc111b2`, `bfffcd5`):
  - Burger was `position:absolute; top:50%` overlapping the stacked CTA row on mobile → now in-flow top-right of logo row (`position: static; margin-left: auto`).
  - Burger/menu now available ≤900px (was ≤768 only) — previously 769–900px had links hidden and no burger (menu inaccessible).
  - Menu closes on outside tap (document click handler).
  - Portrait/mobile compact nav: `nav-menu` wraps links+CTA; ≤900px nav is logo+burger only (56px, no stacked CTA). Open menu shows links + CTA in one dropdown panel. JS closes on any `.nav-menu a` click.
  - **Deploy pending for bfffcd5**: Coolify MCP returned 500 on list/deploy; live site still on dc111b2-era behavior until deploy completes. Verify after Coolify recovers: 390×844 portrait shows compact nav (56px), burger opens menu with links+CTA.
- Note: earlier deploy `j2e0l5aijkk0ixbqzmaetbvq` (cf4d0cd) was stuck in_progress ~50 min (no-cache rebuild) and was cancelled by user action; it did not block site uptime.
- Environment note (2026-11-21): shell tool output-write broke once (ENOSPC then harness temp ENOENT) — recovered after recreating `~/.local/share/opencode/shell` dir; coolify `deploy({wait:true})` times out on long builds, use `listAppDeployments` to poll.

### Homepage mobile layout — nested sections fixed (2026-11-21)

- User sent screenshot `/tmp/bfedeb02-280c-4b65-b6a8-64f029a3c2fa.jpg` (1080×2303, Android) asking to fix mobile layout; model cannot read images, so fixed from DOM audit.
- Found real HTML bug: `<section id="agentes">` (website/index.html:373) and its `.inner` div were never closed before `<section id="customizacao">`. All later sections + footer were nested inside `#agentes` → double padding, inset backgrounds, `agentes` section 16778px tall, page 20261px.
- Fix commit `240be03`: added `</div></section>` after the last `.g2` card. Tag stack now balanced.
- Live deploy `manh6cj1yi6em3hdp5e8bxbz` (240be03) finished. Verified 390×844: all 10 sections full-width 390px, `agentes` 2416px (was 16778), page 18033px (was 20261), no horizontal overflow.
- Additional mobile compacting (commit `00a467d`, deployed `gvjttimznd2pnq9qjrgxjwia`): ≤768px section padding 96→48px, hero padding 80/60→64/40px + `min-height:auto`, `.section-desc` margin 48→24px. Page 19007→17677px @360px. Verified live.
- Caveat: could not visually confirm screenshot problem (no image input in model/subagents, chafa/pixel analysis inconclusive). User resent image 4×; if specific symptom remains, need text description.

### Dashboard ARVO toggle — stale deploy (2026-11-21)
- Source verified: `aios/dashboard/templates/dashboard.html:10` already points to `/dashboard/control-center`; only `/funnels/advisor` link in that template is line 47 (separate "Abrir orientador comercial" button).
- Root cause of live hover URL `/funnels/advisor`: Coolify app `38908ddf-a875-4105-a93f-a4570513911f` last successful deploy was `dc111b2` (before fix `c298361`). Build `biou1fkheuidydmzzw0p5flv` (bfffcd5) stuck `in_progress` ~2h, two HEAD deploys queued behind it.
- Action: cancelled stuck build `biou1fkheuidydmzzw0p5flv`; queued `2pnvysqsu00lxwmwlmo3rdhj` finished 14:09 with commit `e766c56` (includes `c298361`). Next queued deploy `1ubgtgavjg0ya4frmoasqvo9` finished 14:13 with `bdb86ad`.
- Also fixed (commit `bdb86ad`, pushed): `aios/integrations/arvo/routes.py` SSO endpoint used undefined `jwt` and `_PATH` → NameError at runtime; added local imports. Deployed.
- Remaining verification: live hover URL on `/dashboard` after hard refresh (auth-gated, not checked via curl). If still `/funnels/advisor`, check browser cache or proxy cache.
