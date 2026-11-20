## pending work handoff

### ICM-X full architecture rollout (phased) - COMPLETE ✓

1. Persistence/recovery: stage attempts stored in `WorkflowRun.outputs` (`_icm_stage_attempts`), idempotent resume via `resume_outputs`/`resume_status` — test added (`tests/test_workflow_resume_icm.py`) and passes.
2. Approvals: `bind_approval()` wired into both workflow stage execution paths, approval ID + fingerprint recorded in attempt dict.
3. Selective reruns: `invalidate_dependents()` transitive-dependency resolver + test (`tests/test_icm_checkpoint.py`).
4. Benchmarking: `record_run_metrics()` cost/latency/tokens per run in `_persist` output column.
5. Versioned workspace completion: `data/tenants/default/workspaces/b2b_lead_research` with L0-L3 stages + stage manifests (company_research, lead_qualification) already seeded with version 1.0.0.
6. Final: run full ICM/workflow suite and document rollout — 25 tests pass (24 existing + 1 new resume-idempotency integration test).

**All phases complete.** No further DB/schema changes needed; package is inert until explicitly called per architectural boundary docs.
