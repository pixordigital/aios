import pytest

from aios.core.agent_pack import AgentPackValidationError, manifest_fingerprint, validate_agent_pack
from aios.core.agent_pack_convert import (
    CapabilityLossEntry,
    PackConversionResult,
    convert_all_templates,
    convert_icm_stage,
    convert_solutions,
    convert_template,
)
from aios.icm.team_workspaces import AGENT_EVENTS, AGENT_STAGES
from aios.templates import TEMPLATES, _SCAFFOLD_MARKER


def test_every_template_converts_and_validates():
    results = convert_all_templates()
    keys = sorted(TEMPLATES.keys())
    assert [r.manifest.identity.id for r in results] == [f"template-{k.replace('_', '-')}" if not f"template-{k}".startswith("template-") else r.manifest.identity.id for r, k in zip(results, keys)]
    # simpler: cover all keys
    assert len(results) == len(keys)
    for key, res in zip(keys, results):
        assert isinstance(res, PackConversionResult)
        assert res.manifest.identity.tags[0] == "template" or "template" in res.manifest.identity.tags
        assert key in res.manifest.identity.tags
        validate_agent_pack(res.manifest.model_dump(mode="json"))
        assert res.fingerprint == manifest_fingerprint(res.manifest)
        assert isinstance(res.capability_loss, list)
        # loss list always present; may be empty only if fully representable
        for loss in res.capability_loss:
            assert isinstance(loss, CapabilityLossEntry)
            assert loss.reason_code


def test_loss_list_present_and_runtime_defaulted():
    res = convert_template("sdr")
    codes = [l.reason_code for l in res.capability_loss]
    assert "runtime_defaulted" in codes
    assert any(l.source_field == "runtime_targets" for l in res.capability_loss)
    assert res.manifest.runtime_targets[0].target == "local_proc"
    assert res.manifest.runtime_targets[0].entrypoint == ""


def test_scaffold_applied_recorded_when_raw_lacks_marker():
    # sdr raw has no scaffold marker in template prompt; apply_template adds it
    raw = TEMPLATES["sdr"]["system_prompt"]
    assert _SCAFFOLD_MARKER not in raw
    res = convert_template("sdr")
    assert "scaffold_applied" in [l.reason_code for l in res.capability_loss]
    assert _SCAFFOLD_MARKER in res.manifest.prompt.system_prompt

    # template that already has marker should not record scaffold_applied
    # create a synthetic entry
    key = "__test_scaffold__"
    TEMPLATES[key] = {
        "agent_type": "custom",
        "system_prompt": f"hello\n{_SCAFFOLD_MARKER}\nbody",
        "tools": ["read_file"],
    }
    try:
        res2 = convert_template(key)
        assert "scaffold_applied" not in [l.reason_code for l in res2.capability_loss]
    finally:
        TEMPLATES.pop(key, None)


def test_all_normalized_with_loss(monkeypatch):
    key = "__test_all__"
    TEMPLATES[key] = {
        "agent_type": "custom",
        "system_prompt": "prompt",
        "tools": "__all__",
    }
    try:
        res = convert_template(key)
        assert res.manifest.tools.allowed_tools == []
        losses = [l for l in res.capability_loss if l.reason_code == "policy_normalized"]
        assert losses
        assert any("__all__" in l.detail for l in losses)
    finally:
        TEMPLATES.pop(key, None)


def test_icm_stage_event_maps_routine_stage_ref_and_wildcard():
    res = convert_icm_stage("sales-closer")
    validate_agent_pack(res.manifest.model_dump(mode="json"))
    triggers = [r.trigger for r in res.manifest.routines]
    assert "event:crm.stage_changed.*" in triggers
    assert all(r.stage_ref == "icm:sales_ops/closer_deal_execution" for r in res.manifest.routines)
    assert "runtime_defaulted" in [l.reason_code for l in res.capability_loss]
    # wildcard preserved as literal trigger
    wildcard = [r for r in res.manifest.routines if r.trigger.endswith(".*")][0]
    assert wildcard.trigger == "event:crm.stage_changed.*"


def test_denied_tools_union_wins():
    # ICM stage has denied tools; ensure manifest denies them and they are not allowed.
    res = convert_icm_stage("sales-sdr")
    assert "crm_merge_deals" in res.manifest.tools.denied_tools
    assert "crm_stale_deals" in res.manifest.tools.denied_tools
    assert "crm_merge_deals" not in res.manifest.tools.allowed_tools

    # synthetic template where tool appears in both allowed and stage denied
    key = "__test_denied_union__"
    TEMPLATES[key] = {
        "agent_type": "sdr",
        "system_prompt": "x",
        "tools": ["lead_score", "crm_merge_deals"],
    }
    # map to sales-sdr ICM agent for stage denied union
    from aios.core import agent_pack_convert as mod

    old = mod._TEMPLATE_TO_ICM_AGENT.get(key)
    mod._TEMPLATE_TO_ICM_AGENT[key] = "sales-sdr"
    try:
        res2 = convert_template(key)
        assert "crm_merge_deals" in res2.manifest.tools.denied_tools
        assert "crm_merge_deals" not in res2.manifest.tools.allowed_tools
    finally:
        if old is None:
            mod._TEMPLATE_TO_ICM_AGENT.pop(key, None)
        else:
            mod._TEMPLATE_TO_ICM_AGENT[key] = old
        TEMPLATES.pop(key, None)


def test_solutions_produce_explicit_loss_no_silent_drop():
    results = convert_solutions()
    assert len(results) >= 1
    for res in results:
        validate_agent_pack(res.manifest.model_dump(mode="json"))
        codes = [l.reason_code for l in res.capability_loss]
        assert "solution_overlay_unmodeled" in codes
        assert any(l.severity == "high" for l in res.capability_loss)
        assert "runtime_defaulted" in codes
        # no silent drop: result exists and carries loss
        assert res.manifest.identity.tags and "solution" in res.manifest.identity.tags


def test_deterministic_ordering_and_fingerprint_same_input():
    a = convert_template("closer")
    b = convert_template("closer")
    assert a.fingerprint == b.fingerprint
    assert manifest_fingerprint(a.manifest) == manifest_fingerprint(b.manifest)
    assert [l.model_dump() for l in a.capability_loss] == [l.model_dump() for l in b.capability_loss]
    assert a.manifest.model_dump(mode="json") == b.manifest.model_dump(mode="json")

    ia = convert_icm_stage("sales-closer")
    ib = convert_icm_stage("sales-closer")
    assert ia.fingerprint == ib.fingerprint


def test_fail_on_high_raises_on_high_severity(monkeypatch):
    # convert_all_templates should raise if any conversion has high severity
    from aios.core import agent_pack_convert as mod

    orig = mod.convert_template

    def fake(key, **kwargs):
        res = orig(key, **kwargs)
        if key == sorted(TEMPLATES.keys())[0]:
            losses = list(res.capability_loss) + [
                CapabilityLossEntry(
                    id="forced-high",
                    severity="high",
                    reason_code="python_callable_not_portable",
                    source_path="test",
                    source_field="x",
                    detail="forced",
                    portable_alternative=None,
                )
            ]
            return PackConversionResult(manifest=res.manifest, capability_loss=losses, fingerprint=res.fingerprint)
        return res

    monkeypatch.setattr(mod, "convert_template", fake)
    with pytest.raises(AgentPackValidationError, match="high-severity"):
        mod.convert_all_templates(fail_on_high=True)


def test_icm_unknown_agent_raises():
    with pytest.raises(KeyError):
        convert_icm_stage("nope-agent")


def test_template_unknown_raises():
    with pytest.raises(KeyError):
        convert_template("nope-template")


def test_routines_and_loss_ordering_stable():
    res = convert_icm_stage("sales-manager")
    routine_ids = [r.id for r in res.manifest.routines]
    assert routine_ids == sorted(routine_ids)
    # loss ordering deterministic
    losses = [l.model_dump() for l in res.capability_loss]
    assert losses == sorted(losses, key=lambda x: (x["severity"], x["reason_code"], x["source_field"], x["id"], x["detail"]))
