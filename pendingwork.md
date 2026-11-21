## pending work handoff

### ICM-X full architecture rollout (phased) - COMPLETE ✓

1. Persistence/recovery: stage attempts stored in `WorkflowRun.outputs` (`_icm_stage_attempts`), idempotent resume via `resume_outputs`/`resume_status` — test added (`tests/test_workflow_resume_icm.py`) and passes.
2. Approvals: `bind_approval()` wired into both workflow stage execution paths, approval ID + fingerprint recorded in attempt dict.
3. Selective reruns: `invalidate_dependents()` transitive-dependency resolver + test (`tests/test_icm_checkpoint.py`).
4. Benchmarking: `record_run_metrics()` cost/latency/tokens per run in `_persist` output column.
5. Versioned workspace completion: `data/tenants/default/workspaces/b2b_lead_research` with L0-L3 stages + stage manifests (company_research, lead_qualification) already seeded with version 1.0.0.
6. Final: run full ICM/workflow suite and document rollout — 25 tests pass (24 existing + 1 new resume-idempotency integration test).

**All phases complete.** No further DB/schema changes needed; package is inert until explicitly called per architectural boundary docs.

### AIOS homepage nav — IN PROGRESS (2026-11-21)

- Root cause hamburger invisible on mobile: `.nav-burger { display: none }` had no `@media` override; no JS toggle/open state existed.
- Fixed in `website/index.html` (commit `cf4d0cd`):
  - `.nav-burger { display: flex }` under `@media (max-width: 768px)`.
  - `nav.open .links` → full-width column panel (absolute, below pill, column, rounded, blur bg).
  - `.nav-burger.open span` X→open animation (rotate/translate/opacity).
  - JS: burger click toggles `nav.open` + burger `open`; link click closes menu.
- Prior fixes also committed: orphaned mobile CSS given `@media (max-width: 768px)` wrapper (`ab910ec`), `max-width: 100vw`→`100%` (`83b4664`), grid `min-width: 0` (`bdc73e7`), cache-bust comment (`c43d7e6`).
- Deploy state: Coolify app `38908ddf-a875-4105-a93f-a4570513911f` (pixor-aios), latest deploy `j2e0l5aijkk0ixbqzmaetbvq` (commit `cf4d0cd`) was IN_PROGRESS at last check; `deploy({wait:true})` timed out.
- Verification pending: after deploy finishes, check http://178.105.181.38:8777/ — burger visible ≤768px, tap opens full-width column menu, link tap closes.
- Environment note (2026-11-21): shell tool output-write broke (ENOSPC then harness temp ENOENT); claude-code Bash MCP + coolify diagnose/deploy timing out. Retry later; do not assume deploy failures from these errors.

### AIOS homepage nav — RESOLVED (verified via source + deployed HTML curl)

- Deployed HTML at 178.105.181.38:8777 was stale then refreshed: after deploy of `c43d7e6` + `nlffhxd2`, curl showed fresh markup (`<!-- layout fixes -->`, `@media (max-width: 768px)/(max-width: 900px)` only, `max-width: 100%`, `min-width: 0`, `nav-burger` present, burger CSS `display: none` base only → burger never visible on mobile).
- Additional fix in `cf4d0cd` (committed + pushed, awaiting Coolify deploy): burger `display:flex` at ≤768px, `nav.open .links` open panel, X animation, JS toggle.
