from aios.icm.checkpoint import record_stage_attempt, load_stage_attempts, bind_approval, invalidate_dependents, record_run_metrics


def test_record_stage_attempt_is_idempotent_for_same_fingerprint():
    attempts = {}
    prov = {"stage_id": "s", "manifest_fingerprint": "fp1"}
    first = record_stage_attempt(attempts, "node1", prov, "done")
    second = record_stage_attempt(attempts, "node1", prov, "done")
    assert first is second
    assert attempts["node1"]["manifest_fingerprint"] == "fp1"


def test_record_stage_attempt_allows_new_fingerprint():
    attempts = {}
    record_stage_attempt(attempts, "node1", {"manifest_fingerprint": "fp1"}, "done")
    record_stage_attempt(attempts, "node1", {"manifest_fingerprint": "fp2"}, "done")
    assert attempts["node1"]["manifest_fingerprint"] == "fp2"


def test_load_stage_attempts_reads_nested_dict():
    outputs = {"_icm_stage_attempts": {"node1": {"status": "done"}}}
    assert load_stage_attempts(outputs)["node1"]["status"] == "done"
    assert load_stage_attempts(None) == {}


def test_bind_approval_records_fingerprint():
    attempt = {"manifest_fingerprint": "fp1"}
    bound = bind_approval(attempt, "appr-1")
    assert bound["approval_id"] == "appr-1"
    assert bound["approved_fingerprint"] == "fp1"


def test_invalidate_dependents_transitive():
    dependents = {"a": ["b"], "b": ["c"], "c": []}
    assert invalidate_dependents("a", dependents) == {"b", "c"}
    assert invalidate_dependents("c", dependents) == set()


def test_record_run_metrics_merges_values():
    metrics = {}
    record_run_metrics(metrics, cost_usd=0.05, latency_ms=120, tokens=1000)
    assert metrics == {"cost_usd": 0.05, "latency_ms": 120, "tokens": 1000}
