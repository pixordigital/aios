## pending work handoff

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
