import base64
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aios.core.agent_pack import AgentPackValidationError, validate_agent_pack
from aios.core.agent_pack_export import export_agent_pack
from aios.core.agent_pack_install import (
    InstallConsent,
    apply_install,
    build_bundle_signature,
    inspect_bundle,
    plan_install,
    rollback_install,
    uninstall,
)


def _manifest():
    return validate_agent_pack({
        "schema_version": "1.0.0",
        "version": "1.0.0",
        "identity": {
            "id": "sales-sdr",
            "name": "Sales SDR",
            "agent_type": "sdr",
            "description": "Qualify leads",
            "owner": "team",
            "tags": ["sales"],
        },
        "prompt": {
            "system_prompt": "You are an SDR. Be helpful.",
            "variables": ["company"],
            "scaffold_required": True,
        },
        "tools": {
            "allowed_tools": ["crm_lookup"],
            "denied_tools": ["delete_db"],
            "risk_classes": {"crm_lookup": "read", "send_email": "side_effect"},
        },
        "routines": [],
        "approvals": {
            "mode": "ask_tools",
            "required_for": ["send_email"],
            "approval_ttl_seconds": 300,
            "explicit_preapproved_allowed": False,
        },
        "memory_scope": {
            "scopes": ["conversation", "agent"],
            "max_short_term_messages": 100,
            "long_term_enabled": True,
            "episodic_enabled": True,
            "redact_patterns": [],
        },
        "runtime_targets": [
            {"target": "local_proc", "entrypoint": "main:run", "image": None, "resources": {}}
        ],
        "changelog": [{"version": "1.0.0", "date": "2026-11-25", "summary": "init", "author": "pixor"}],
        "provenance": {
            "source": "git:test",
            "created_by": "tester",
            "created_at": "2026-11-25T00:00:00Z",
            "checksum_sha256": None,
            "signature": None,
            "parent_fingerprint": None,
        },
    })


def _export_bundle(tmp_path: Path, target="codex"):
    m = _manifest()
    out = tmp_path / f"bundle-{target}"
    export_agent_pack(m, target=target, output_dir=out)
    return out


def _sha256_bytes(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def _canonical_json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def _rewrite_bundle_manifest(bundle_dir: Path) -> dict:
    manifest_path = bundle_dir / "bundle.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = []
    for item in manifest.get("files", []):
        p = bundle_dir / item["path"]
        raw = p.read_bytes()
        files.append({"path": item["path"], "sha256": _sha256_bytes(raw), "bytes": len(raw)})
    files = sorted(files, key=lambda x: x["path"])
    manifest["files"] = files
    manifest["bundle_sha256"] = _sha256_bytes(_canonical_json(files).encode("utf-8"))
    manifest_path.write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
    return manifest


def _sign_bundle_dir(bundle_dir: Path, *, key_id="k1", priv_pem=None):
    if priv_pem is None:
        priv_pem, _ = _make_keypair()
    manifest = json.loads((bundle_dir / "bundle.manifest.json").read_text(encoding="utf-8"))
    prov_path = bundle_dir / "provenance.json"
    provenance = json.loads(prov_path.read_text(encoding="utf-8"))
    sig = build_bundle_signature(bundle_manifest=manifest, provenance=provenance, key_id=key_id, private_key_pem=priv_pem)
    src = dict(provenance.get("source_provenance") or {})
    src["signature"] = sig
    provenance["source_provenance"] = src
    provenance["unsigned"] = False
    prov_path.write_text(_canonical_json(provenance) + "\n", encoding="utf-8")
    manifest = _rewrite_bundle_manifest(bundle_dir)
    # keep provenance.bundle_sha256 aligned to manifest for clarity; verifier binds manifest anyway
    provenance["bundle_sha256"] = manifest["bundle_sha256"]
    prov_path.write_text(_canonical_json(provenance) + "\n", encoding="utf-8")
    manifest = _rewrite_bundle_manifest(bundle_dir)
    return manifest, provenance, priv_pem


def _consent(plan, *, actor="tester", phrase="I CONSENT", allow_unsigned=False, cap_ack=True, force=False, plan_hash=None, bundle_hash=None, target=None):
    return InstallConsent(
        actor=actor,
        bundle_hash=bundle_hash or plan.bundle_hash,
        target=target or plan.target,
        plan_hash=plan_hash or plan.plan_hash,
        capability_loss_ack=cap_ack,
        consent_phrase=phrase,
        timestamp="2026-11-25T00:00:00Z",
        allow_unsigned=allow_unsigned,
        force=force,
    )


def test_inspect_plan_deterministic(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    insp1 = inspect_bundle(bundle)
    insp2 = inspect_bundle(bundle)
    assert insp1 == insp2
    assert insp1["hashes_ok"] is True
    assert insp1["trust"] == "unsigned"

    target_root = tmp_path / "target"
    records = tmp_path / "records"
    p1 = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    p2 = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    assert p1.model_dump(mode="json") == p2.model_dump(mode="json")
    assert len(p1.plan_hash) == 64
    assert p1.requires_unsigned_ack is True
    assert isinstance(p1.capability_loss, list)


def test_plan_diff_create_modify_noop(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    p1 = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    ops = {o.rel_path: o.op for o in p1.operations}
    assert "AGENTS.md" in ops
    assert all(op in {"create", "modify", "noop"} for op in ops.values())
    assert any(op == "create" for op in ops.values())

    # apply once
    c = _consent(p1, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True)
    r = apply_install(p1, consent=c, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert r.ok, r.errors

    # second plan should be noop
    p2 = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    assert all(o.op == "noop" for o in p2.operations)

    # modify a file
    (target_root / "AGENTS.md").write_text("changed\n", encoding="utf-8")
    p3 = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    mod = [o for o in p3.operations if o.rel_path == "AGENTS.md"][0]
    assert mod.op == "modify"
    assert mod.backup_path


def test_tampered_hash_blocked(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    agents = bundle / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8") + "\nTAMPER\n", encoding="utf-8")
    with pytest.raises(AgentPackValidationError):
        plan_install(bundle, "codex", target_root=tmp_path / "t", records_dir=tmp_path / "r")


def test_unsigned_blocked_without_explicit_allow(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    plan = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    c = _consent(plan, phrase="I CONSENT", allow_unsigned=False)
    res = apply_install(plan, consent=c, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert not res.ok
    assert any("UNSIGNED_RISK_ACCEPTED" in e or "allow_unsigned" in e for e in res.errors)
    assert not (target_root / "AGENTS.md").exists()


def test_unsigned_allowed_with_loud_warning(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    plan = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    c = _consent(plan, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True)
    res = apply_install(plan, consent=c, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert res.ok, res.errors
    assert any("UNSIGNED" in w for w in res.warnings)


def test_consent_required_and_mismatch_rejected(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    plan = plan_install(bundle, "codex", target_root=target_root, records_dir=records)

    bad_hash = _consent(plan, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True, plan_hash="0" * 64)
    r1 = apply_install(plan, consent=bad_hash, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert not r1.ok
    assert not any(target_root.rglob("*"))

    bad_phrase = _consent(plan, phrase="yes", allow_unsigned=True)
    r2 = apply_install(plan, consent=bad_phrase, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert not r2.ok
    assert not (target_root / "AGENTS.md").exists()

    bad_ack = _consent(plan, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True, cap_ack=False)
    r3 = apply_install(plan, consent=bad_ack, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert not r3.ok


def test_apply_writes_only_allowed_roots_and_records(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "claude_code")
    target_root = tmp_path / "home" / ".claude"
    records = tmp_path / "records"
    outside = tmp_path / "outside"
    outside.mkdir()
    plan = plan_install(bundle, "claude_code", target_root=target_root, records_dir=records)
    consent = _consent(plan, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True)
    res = apply_install(plan, consent=consent, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert res.ok, res.errors
    assert res.install_record_path
    assert Path(res.install_record_path).resolve().is_relative_to(records.resolve())
    assert Path(res.audit_log_path).resolve().is_relative_to(records.resolve())
    # all written files under target_root or records
    allowed = {target_root.resolve(), records.resolve()}
    for p in tmp_path.rglob("*"):
        if p.is_dir():
            continue
        rp = p.resolve()
        assert any(rp.is_relative_to(a) for a in allowed) or rp.is_relative_to(bundle.resolve())
    # install record contains metadata only
    rec = json.loads(Path(res.install_record_path).read_text(encoding="utf-8"))
    assert rec["bundle_hash"] == plan.bundle_hash
    assert rec["status"] == "applied"
    assert "system_prompt" not in json.dumps(rec)


def test_rollback_restores(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    plan = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    consent = _consent(plan, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True)
    res = apply_install(plan, consent=consent, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert res.ok, res.errors

    # modify installed file and reinstall modified bundle? easier: create new bundle with changed content
    m = _manifest().model_dump(mode="json")
    m["prompt"]["system_prompt"] = "changed prompt"
    m["version"] = "1.0.1"
    m["changelog"].append({"version": "1.0.1", "date": "2026-11-25", "summary": "change", "author": "pixor"})
    m2 = validate_agent_pack(m)
    bundle2 = tmp_path / "bundle2"
    export_agent_pack(m2, target="codex", output_dir=bundle2)
    plan2 = plan_install(bundle2, "codex", target_root=target_root, records_dir=records)
    res2 = apply_install(plan2, consent=_consent(plan2, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert res2.ok, res2.errors
    assert "changed prompt" in (target_root / "AGENTS.md").read_text(encoding="utf-8")

    rb = rollback_install(res2.install_record_path, consent=InstallConsent(
        actor="tester", bundle_hash=plan2.bundle_hash, target=plan2.target, plan_hash=plan2.plan_hash,
        capability_loss_ack=True, consent_phrase="ROLLBACK", timestamp="2026-11-25T00:00:01Z", allow_unsigned=True,
    ), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert rb.ok, rb.errors
    assert "changed prompt" not in (target_root / "AGENTS.md").read_text(encoding="utf-8")


def test_drift_requires_force(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    plan = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    res = apply_install(plan, consent=_consent(plan, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert res.ok
    # drift
    (target_root / "AGENTS.md").write_text("user edit\n", encoding="utf-8")
    rb = rollback_install(res.install_record_path, consent=InstallConsent(
        actor="tester", bundle_hash=plan.bundle_hash, target=plan.target, plan_hash=plan.plan_hash,
        capability_loss_ack=True, consent_phrase="ROLLBACK", timestamp="2026-11-25T00:00:01Z", allow_unsigned=True, force=False,
    ), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert not rb.ok
    assert any("drift" in e.lower() for e in rb.errors)

    rb2 = rollback_install(res.install_record_path, consent=InstallConsent(
        actor="tester", bundle_hash=plan.bundle_hash, target=plan.target, plan_hash=plan.plan_hash,
        capability_loss_ack=True, consent_phrase="ROLLBACK FORCE", timestamp="2026-11-25T00:00:02Z", allow_unsigned=True, force=True,
    ), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert rb2.ok, rb2.errors


def test_traversal_and_symlink_escape_rejected(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    # traversal in target root not possible via API, but ensure bundle file path traversal rejected by crafting bad manifest
    bad = tmp_path / "badbundle"
    bad.mkdir()
    # copy legit bundle
    import shutil
    shutil.copytree(bundle, bad / "b")
    bdir = bad / "b"
    manifest_path = bdir / "bundle.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../escape.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    insp = inspect_bundle(bdir)
    assert insp["trust"] == "invalid"
    assert insp["hashes_ok"] is False
    with pytest.raises(AgentPackValidationError):
        plan_install(bdir, "codex", target_root=tmp_path / "t", records_dir=tmp_path / "r")

    # symlink escape in target
    target_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (target_root / "AGENTS.md").symlink_to(outside / "x")
    with pytest.raises(AgentPackValidationError):
        plan_install(bundle, "codex", target_root=target_root, records_dir=records)


def test_no_subprocess_network(monkeypatch, tmp_path: Path):
    import subprocess, socket
    def boom(*a, **k):
        raise AssertionError("subprocess/network disallowed")
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)

    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    plan = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    res = apply_install(plan, consent=_consent(plan, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert res.ok, res.errors


def test_uninstall_same_consent_gate(tmp_path: Path):
    bundle = _export_bundle(tmp_path, "codex")
    target_root = tmp_path / "target"
    records = tmp_path / "records"
    plan = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    res = apply_install(plan, consent=_consent(plan, phrase="I CONSENT UNSIGNED_RISK_ACCEPTED", allow_unsigned=True), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert res.ok
    bad = uninstall(res.install_record_path, consent=InstallConsent(
        actor="tester", bundle_hash=plan.bundle_hash, target=plan.target, plan_hash=plan.plan_hash,
        capability_loss_ack=True, consent_phrase="ROLLBACK", timestamp="2026-11-25T00:00:01Z", allow_unsigned=True,
    ), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert not bad.ok
    ok = uninstall(res.install_record_path, consent=InstallConsent(
        actor="tester", bundle_hash=plan.bundle_hash, target=plan.target, plan_hash=plan.plan_hash,
        capability_loss_ack=True, consent_phrase="UNINSTALL", timestamp="2026-11-25T00:00:01Z", allow_unsigned=True,
    ), records_dir=records, audit_log_path=records / "audit.jsonl")
    assert ok.ok, ok.errors
    assert not (target_root / "AGENTS.md").exists()


def test_valid_ed25519_signature_trusted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    _, pub_pem = _make_keypair()
    # sign with matching private key generated inside helper? we need private pem used; easier: generate, sign, set trusted to its pub.
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="trusted-1", priv_pem=priv_pem)
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({"trusted-1": pub_pem}))

    insp = inspect_bundle(bundle)
    assert insp["hashes_ok"] is True
    assert insp["trust"] == "trusted"

    target_root = tmp_path / "target"
    records = tmp_path / "records"
    plan = plan_install(bundle, "codex", target_root=target_root, records_dir=records)
    assert plan.trust == "trusted"
    assert plan.requires_unsigned_ack is False
    consent = _consent(plan, phrase="I CONSENT", allow_unsigned=False)
    res = apply_install(plan, consent=consent, records_dir=records, audit_log_path=records / "audit.jsonl")
    assert res.ok, res.errors
    assert not any("UNSIGNED" in w for w in res.warnings)


def test_tampered_signed_bundle_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="trusted-1", priv_pem=priv_pem)
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({"trusted-1": pub_pem}))

    # tamper file content after signing
    agents = bundle / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8") + "\nTAMPER\n", encoding="utf-8")
    insp = inspect_bundle(bundle)
    assert insp["hashes_ok"] is False
    assert insp["trust"] == "invalid"
    with pytest.raises(AgentPackValidationError):
        plan_install(bundle, "codex", target_root=tmp_path / "t", records_dir=tmp_path / "r")


def test_invalid_signature_tamper_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="trusted-1", priv_pem=priv_pem)
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({"trusted-1": pub_pem}))

    prov_path = bundle / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    sig_b64 = prov["source_provenance"]["signature"]["signature_b64"]
    raw = bytearray(base64.b64decode(sig_b64))
    raw[0] ^= 0x01
    prov["source_provenance"]["signature"]["signature_b64"] = base64.b64encode(bytes(raw)).decode("ascii")
    prov_path.write_text(_canonical_json(prov) + "\n", encoding="utf-8")
    _rewrite_bundle_manifest(bundle)  # keep file hashes consistent; signature itself invalid

    insp = inspect_bundle(bundle)
    assert insp["hashes_ok"] is True
    assert insp["trust"] == "invalid"
    assert any("invalid signature" in r.lower() for r in insp["trust_reasons"])
    with pytest.raises(AgentPackValidationError):
        plan_install(bundle, "codex", target_root=tmp_path / "t", records_dir=tmp_path / "r")


def test_unknown_key_or_missing_config_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="unknown-1", priv_pem=priv_pem)

    monkeypatch.delenv("AIOS_AGENT_PACK_TRUSTED_KEYS", raising=False)
    monkeypatch.delenv("AIOS_AGENT_PACK_TRUSTED_KEYS_FILE", raising=False)
    insp = inspect_bundle(bundle)
    assert insp["trust"] == "unsigned"
    assert any("no trusted keys configured" in r.lower() for r in insp["trust_reasons"])

    other_priv = Ed25519PrivateKey.generate()
    other_pub = other_priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({"different-key": other_pub}))
    insp2 = inspect_bundle(bundle)
    assert insp2["trust"] == "unsigned"
    assert any("unknown signing key_id" in r.lower() for r in insp2["trust_reasons"])


def test_old_trusted_key_format_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="old-key", priv_pem=priv_pem)
    # Old format: {key_id: pem}
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({"old-key": pub_pem}))
    insp = inspect_bundle(bundle)
    assert insp["trust"] == "trusted"
    assert insp["key_id"] == "old-key"
    assert insp["trusted_key_count"] == 1


def test_revoked_key_in_trusted_config_not_trusted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="k-rev", priv_pem=priv_pem)
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({
        "k-rev": {"public_key_pem": pub_pem, "revoked": True, "purpose": "agent_pack_bundle"}
    }))
    insp = inspect_bundle(bundle)
    assert insp["trust"] != "trusted"
    assert any("revoked" in r.lower() for r in insp["trust_reasons"])
    with pytest.raises(AgentPackValidationError):
        plan_install(bundle, "codex", target_root=tmp_path / "t", records_dir=tmp_path / "r")


def test_expired_key_not_trusted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="k-exp", priv_pem=priv_pem)
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({
        "k-exp": {
            "public_key_pem": pub_pem,
            "not_after": "2000-01-01T00:00:00Z",
            "purpose": "agent_pack_bundle",
        }
    }))
    insp = inspect_bundle(bundle)
    assert insp["trust"] != "trusted"
    assert any("expired" in r.lower() for r in insp["trust_reasons"])
    with pytest.raises(AgentPackValidationError):
        plan_install(bundle, "codex", target_root=tmp_path / "t", records_dir=tmp_path / "r")


def test_revocation_file_blocks_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="k-file-rev", priv_pem=priv_pem)
    rev_file = tmp_path / "revoked.json"
    rev_file.write_text(json.dumps(["k-file-rev"]), encoding="utf-8")
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({"k-file-rev": pub_pem}))
    monkeypatch.setenv("AIOS_AGENT_PACK_REVOKED_KEYS_FILE", str(rev_file))
    insp = inspect_bundle(bundle)
    assert insp["trust"] != "trusted"
    assert any("revoked" in r.lower() for r in insp["trust_reasons"])
    assert insp["revocation_checked"] is True


def test_trust_log_appended_when_env_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = _export_bundle(tmp_path, "codex")
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    _sign_bundle_dir(bundle, key_id="k-log", priv_pem=priv_pem)
    log_path = tmp_path / "trust-log.jsonl"
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUSTED_KEYS", json.dumps({"k-log": pub_pem}))
    monkeypatch.setenv("AIOS_AGENT_PACK_TRUST_LOG", str(log_path))

    insp = inspect_bundle(bundle)
    assert insp["trust"] == "trusted"
    assert insp["transparency_logged"] is True
    assert log_path.exists()
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    assert any(r.get("key_id") == "k-log" and r.get("trust") == "trusted" for r in rows)
    assert all("bundle_sha256" in r and "fingerprint" in r and "ts" in r for r in rows)
