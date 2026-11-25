"""Guided local install for AgentPack export bundles.

No remote push, no background/silent install, no network fetch, no shell execution
from bundle, no parity claims. Stdlib only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aios.core.agent_pack import AgentPackValidationError

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except Exception:  # pragma: no cover - dependency declared in pyproject
    serialization = None  # type: ignore[assignment]
    Ed25519PrivateKey = None  # type: ignore[assignment]
    Ed25519PublicKey = None  # type: ignore[assignment]

InstallTarget = Literal["claude_code", "codex", "opencode", "openclaw", "openbot"]
_TARGETS: tuple[str, ...] = ("claude_code", "codex", "opencode", "openclaw", "openbot")
_DEFAULT_TARGET_ROOTS: dict[str, Path] = {
    "claude_code": Path.home() / ".claude",
    "codex": Path.home() / ".codex",
    "opencode": Path.home() / ".config" / "opencode",
    "openclaw": Path.home() / ".openclaw",
    # Conservative default; OpenBot has no canonical Pixor-managed install path yet.
    # Guided local install only, no auto-install/no network.
    "openbot": Path.home() / ".openbot",
}
_DEFAULT_RECORD_DIR = Path.home() / ".local" / "share" / "aios" / "agent-pack-installs"
_DEFAULT_AUDIT_LOG = _DEFAULT_RECORD_DIR / "audit.jsonl"


class InstallConsent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor: str = Field(min_length=1, max_length=255)
    bundle_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    target: InstallTarget
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_loss_ack: bool
    consent_phrase: str = Field(min_length=1, max_length=255)
    timestamp: str = Field(min_length=1, max_length=64)
    allow_unsigned: bool = False
    force: bool = False


class PlannedOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["create", "modify", "noop"]
    rel_path: str
    abs_path: str
    before_hash: str | None = None
    after_hash: str | None = None
    backup_path: str | None = None
    reason: str


class InstallPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_dir: str
    bundle_hash: str
    target: InstallTarget
    target_root: str
    trust: Literal["trusted", "unsigned", "invalid"]
    trust_reasons: list[str]
    capability_loss: list[dict[str, Any]]
    operations: list[PlannedOperation]
    commands_preview: list[str]
    rollback_plan: dict[str, Any]
    plan_hash: str
    requires_capability_loss_ack: bool
    requires_unsigned_ack: bool


class InstallResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    target: InstallTarget
    bundle_hash: str
    plan_hash: str
    install_record_path: str | None
    audit_log_path: str | None
    applied: list[dict[str, Any]]
    rolled_back: bool
    warnings: list[str]
    errors: list[str]


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_json(data: Any) -> str:
    return _sha256_bytes(_canonical_json(data).encode("utf-8"))


_SIGNATURE_ALG_ED25519 = "ed25519"
_TRUSTED_KEYS_ENV = "AIOS_AGENT_PACK_TRUSTED_KEYS"
_TRUSTED_KEYS_FILE_ENV = "AIOS_AGENT_PACK_TRUSTED_KEYS_FILE"
_REVOKED_KEYS_FILE_ENV = "AIOS_AGENT_PACK_REVOKED_KEYS_FILE"
_TRUST_LOG_ENV = "AIOS_AGENT_PACK_TRUST_LOG"
_SIGNING_PRIVATE_KEY_FILE_ENV = "AIOS_AGENT_PACK_SIGNING_PRIVATE_KEY_FILE"


def _b64decode_str(value: str, *, field: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise AgentPackValidationError("invalid base64 value", field=field)
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:
        raise AgentPackValidationError("invalid base64 encoding", field=field) from exc


def _load_pem_public_key(pem: str, *, field: str) -> "Ed25519PublicKey":
    if serialization is None or Ed25519PublicKey is None:
        raise AgentPackValidationError("cryptography Ed25519 support unavailable", field=field)
    if not isinstance(pem, str) or not pem.strip():
        raise AgentPackValidationError("invalid public key PEM", field=field)
    try:
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
    except Exception as exc:
        raise AgentPackValidationError("invalid public key PEM", field=field) from exc
    if not isinstance(key, Ed25519PublicKey):
        raise AgentPackValidationError("public key must be Ed25519", field=field)
    return key


def _load_pem_private_key(pem: str, *, field: str) -> "Ed25519PrivateKey":
    if serialization is None or Ed25519PrivateKey is None:
        raise AgentPackValidationError("cryptography Ed25519 support unavailable", field=field)
    if not isinstance(pem, str) or not pem.strip():
        raise AgentPackValidationError("invalid private key PEM", field=field)
    try:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception as exc:
        raise AgentPackValidationError("invalid private key PEM", field=field) from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise AgentPackValidationError("private key must be Ed25519", field=field)
    return key


def _public_key_pem(key: "Ed25519PublicKey") -> str:
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def _parse_iso8601_utc(value: Any, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AgentPackValidationError("invalid ISO8601 timestamp", field=field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception as exc:
        raise AgentPackValidationError("invalid ISO8601 timestamp", field=field) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_trusted_key_record(item: Any, *, field: str, key_id: str | None = None) -> tuple[str, dict[str, Any]]:
    if isinstance(item, str):
        pem = item
        kid = key_id
        rec: dict[str, Any] = {}
    elif isinstance(item, dict):
        kid = item.get("key_id", key_id)
        pem = item.get("public_key_pem") or item.get("pem") or item.get("public_key")
        rec = dict(item)
    else:
        raise AgentPackValidationError("trusted key entry must be object/string", field=field)

    if not isinstance(kid, str) or not kid.strip():
        raise AgentPackValidationError("trusted key missing key_id", field=f"{field}.key_id")
    kid = kid.strip()
    if not isinstance(pem, str) or not pem.strip():
        raise AgentPackValidationError("trusted key missing public key PEM", field=f"{field}.public_key_pem")
    pem = pem.strip()
    _load_pem_public_key(pem, field=f"{field}.public_key_pem")

    revoked = rec.get("revoked", False)
    if not isinstance(revoked, bool):
        raise AgentPackValidationError("trusted key revoked must be bool", field=f"{field}.revoked")
    purpose = rec.get("purpose")
    if purpose is not None and (not isinstance(purpose, str) or not purpose.strip()):
        raise AgentPackValidationError("trusted key purpose must be string", field=f"{field}.purpose")
    not_before = _parse_iso8601_utc(rec.get("not_before"), field=f"{field}.not_before")
    not_after = _parse_iso8601_utc(rec.get("not_after"), field=f"{field}.not_after")
    if not_before and not_after and not_before > not_after:
        raise AgentPackValidationError("trusted key not_before after not_after", field=f"{field}.not_before")

    return kid, {
        "key_id": kid,
        "public_key_pem": pem,
        "revoked": revoked,
        "not_before": not_before.isoformat().replace("+00:00", "Z") if not_before else None,
        "not_after": not_after.isoformat().replace("+00:00", "Z") if not_after else None,
        "purpose": purpose.strip() if isinstance(purpose, str) else None,
    }


def _normalize_trusted_keys_obj(obj: Any, *, field: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(obj, dict):
        # formats: {"key_id":"PEM"} or {"key_id":{...}} or {"keys":[...]} (legacy/list)
        if "keys" in obj and isinstance(obj["keys"], list):
            items = obj["keys"]
            for i, item in enumerate(items):
                kid, rec = _normalize_trusted_key_record(item, field=f"{field}[{i}]")
                out[kid] = rec
            return out
        for k, v in obj.items():
            kid, rec = _normalize_trusted_key_record(v, field=f"{field}.{k}", key_id=k)
            out[kid] = rec
        return out
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            kid, rec = _normalize_trusted_key_record(item, field=f"{field}[{i}]")
            out[kid] = rec
        return out
    raise AgentPackValidationError("trusted keys must be object/list", field=field)


def _load_trusted_public_keys() -> dict[str, dict[str, Any]]:
    keys: dict[str, dict[str, Any]] = {}
    raw_json = os.getenv(_TRUSTED_KEYS_ENV, "").strip()
    raw_file = os.getenv(_TRUSTED_KEYS_FILE_ENV, "").strip()
    if raw_file:
        p = Path(raw_file).expanduser()
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise AgentPackValidationError(f"cannot read trusted keys file: {exc}", field=_TRUSTED_KEYS_FILE_ENV) from exc
        keys.update(_normalize_trusted_keys_obj(obj, field=_TRUSTED_KEYS_FILE_ENV))
    if raw_json:
        try:
            obj = json.loads(raw_json)
        except Exception as exc:
            raise AgentPackValidationError(f"invalid trusted keys JSON: {exc}", field=_TRUSTED_KEYS_ENV) from exc
        keys.update(_normalize_trusted_keys_obj(obj, field=_TRUSTED_KEYS_ENV))
    return keys


def _trusted_keys_configured() -> bool:
    return bool(os.getenv(_TRUSTED_KEYS_ENV, "").strip() or os.getenv(_TRUSTED_KEYS_FILE_ENV, "").strip())


def _load_revoked_keys() -> set[str]:
    raw_file = os.getenv(_REVOKED_KEYS_FILE_ENV, "").strip()
    if not raw_file:
        return set()
    p = Path(raw_file).expanduser()
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AgentPackValidationError(f"cannot read revoked keys file: {exc}", field=_REVOKED_KEYS_FILE_ENV) from exc

    revoked: set[str] = set()
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            if not isinstance(item, str) or not item.strip():
                raise AgentPackValidationError("revoked key id must be string", field=f"{_REVOKED_KEYS_FILE_ENV}[{i}]")
            revoked.add(item.strip())
        return revoked
    if isinstance(obj, dict):
        # Accept {"key_id": true} or {"revoked":[...]} for local ergonomics; fail closed on bad shape.
        if "revoked" in obj and isinstance(obj["revoked"], list):
            for i, item in enumerate(obj["revoked"]):
                if not isinstance(item, str) or not item.strip():
                    raise AgentPackValidationError("revoked key id must be string", field=f"{_REVOKED_KEYS_FILE_ENV}.revoked[{i}]")
                revoked.add(item.strip())
            return revoked
        for k, v in obj.items():
            if not isinstance(k, str) or not k.strip():
                raise AgentPackValidationError("revoked key id must be string", field=_REVOKED_KEYS_FILE_ENV)
            if v is True:
                revoked.add(k.strip())
            elif v is False:
                continue
            else:
                raise AgentPackValidationError("revoked key value must be bool", field=f"{_REVOKED_KEYS_FILE_ENV}.{k}")
        return revoked
    raise AgentPackValidationError("revoked keys must be list/object", field=_REVOKED_KEYS_FILE_ENV)


def _key_time_reason(rec: dict[str, Any], *, now: datetime) -> str | None:
    nb = rec.get("not_before")
    na = rec.get("not_after")
    if nb:
        nb_dt = _parse_iso8601_utc(nb, field="trusted_key.not_before")
        if nb_dt and now < nb_dt:
            return f"key not yet valid: {rec.get('key_id')}"
    if na:
        na_dt = _parse_iso8601_utc(na, field="trusted_key.not_after")
        if na_dt and now > na_dt:
            return f"key expired: {rec.get('key_id')}"
    return None


def _append_trust_log(entry: dict[str, Any]) -> tuple[bool, str | None]:
    raw_file = os.getenv(_TRUST_LOG_ENV, "").strip()
    if not raw_file:
        return False, None
    p = Path(raw_file).expanduser()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True, None
    except Exception as exc:
        # Best-effort: trust decision unchanged; caller records warning.
        return False, f"trust log write failed: {exc}"


def _content_bundle_sha256(bundle_manifest: dict[str, Any]) -> str:
    """Stable hash over manifest-listed files excluding provenance/manifest envelopes.

    Excluding provenance.json avoids circularity (signature lives in provenance).
    bundle.manifest.json is not listed as a file entry in exports; excluded defensively.
    """
    files = bundle_manifest.get("files", [])
    normalized = []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if path in {"provenance.json", "bundle.manifest.json"}:
            continue
        normalized.append({
            "path": str(path),
            "sha256": str(item.get("sha256") or ""),
            "bytes": int(item.get("bytes") or 0),
        })
    normalized = sorted(normalized, key=lambda x: x["path"])
    return _sha256_json(normalized)


def _signature_payload(bundle_manifest: dict[str, Any], provenance: dict[str, Any]) -> bytes:
    # Deterministic payload bound to verified bundle content and source identity.
    # Do not include signature itself. Uses content hash excluding provenance to
    # avoid circular dependency when embedding signature in provenance.json.
    src = provenance.get("source_provenance") if isinstance(provenance.get("source_provenance"), dict) else {}
    src = dict(src)
    src.pop("signature", None)
    payload = {
        "schema_version": "1.0.0",
        "bundle_content_sha256": _content_bundle_sha256(bundle_manifest),
        "source_pack_fingerprint": str(provenance.get("source_pack_fingerprint") or bundle_manifest.get("source_pack_fingerprint") or ""),
        "target": str(provenance.get("target") or bundle_manifest.get("target") or ""),
        "source_provenance": src,
    }
    return _canonical_json(payload).encode("utf-8")


def build_bundle_signature(*, bundle_manifest: dict[str, Any], provenance: dict[str, Any], key_id: str, private_key_pem: str) -> dict[str, str]:
    """Build ed25519 signature envelope for tests/tooling. No runtime auto-use."""
    if not isinstance(key_id, str) or not key_id.strip():
        raise AgentPackValidationError("key_id required", field="signature.key_id")
    priv = _load_pem_private_key(private_key_pem, field="signature.private_key_pem")
    payload = _signature_payload(bundle_manifest, provenance)
    sig = priv.sign(payload)
    pub_pem = _public_key_pem(priv.public_key())
    return {
        "alg": _SIGNATURE_ALG_ED25519,
        "key_id": key_id.strip(),
        "public_key_pem": pub_pem,
        "payload_sha256": _sha256_bytes(payload),
        "signature_b64": base64.b64encode(sig).decode("ascii"),
    }


def sign_bundle(bundle_dir: str | Path, *, key_id: str, private_key_pem: str | None = None, private_key_file: str | Path | None = None) -> dict[str, Any]:
    """Attach signature to provenance.json. Local-only tooling helper; not install path."""
    bdir = Path(bundle_dir).resolve()
    bundle_manifest, provenance, _, _ = _load_bundle_files(bdir)
    pem = private_key_pem
    if pem is None:
        pk_file = private_key_file or os.getenv(_SIGNING_PRIVATE_KEY_FILE_ENV)
        if not pk_file:
            raise AgentPackValidationError("private key required", field="signature.private_key")
        pem = Path(pk_file).expanduser().read_text(encoding="utf-8")
    sig = build_bundle_signature(bundle_manifest=bundle_manifest, provenance=provenance, key_id=key_id, private_key_pem=pem)
    prov2 = dict(provenance)
    src = dict(prov2.get("source_provenance") or {})
    src["signature"] = sig
    prov2["source_provenance"] = src
    prov2["unsigned"] = False
    # recompute provenance file entry? provenance.json is in bundle manifest; changing it invalidates hashes.
    # For safety/fail-closed, sign_bundle only returns unsigned-updated provenance and signature; caller must regenerate bundle.
    return {"provenance": prov2, "signature": sig, "note": "provenance updated in-memory; regenerate bundle manifest/hashes before install"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_id_fragment(value: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value.strip())
    out = out.strip("-._")
    return out[:80] or "unknown"


def _lexists(path: Path) -> bool:
    return os.path.lexists(str(path))


def _reject_symlink_path(path: Path, field: str) -> None:
    # Reject if path or any existing ancestor component is symlink.
    parts = path.parts
    if path.is_absolute():
        cur = Path(path.anchor)
        iterable = parts[1:]
    else:
        cur = Path(".")
        iterable = parts
    for part in iterable:
        cur = cur / part
        try:
            if _lexists(cur) and cur.is_symlink():
                raise AgentPackValidationError("symlink path rejected", field=field)
        except OSError as exc:
            raise AgentPackValidationError(f"path inspection failed: {exc}", field=field) from exc


def _resolve_under_root(root: Path, rel: str, *, field: str) -> Path:
    if not isinstance(rel, str) or not rel:
        raise AgentPackValidationError("invalid path", field=field)
    if rel.startswith("/") or rel.startswith("\\") or "\\" in rel:
        raise AgentPackValidationError("absolute/backslash path rejected", field=field)
    rp = Path(rel)
    if any(part in {"..", ""} for part in rp.parts):
        raise AgentPackValidationError("path traversal rejected", field=field)
    root_resolved = root.resolve()
    _reject_symlink_path(root_resolved, "target_root")
    target = (root_resolved / rp)
    resolved = target.resolve()
    try:
        resolved.relative_to(root_resolved)
    except Exception as exc:
        raise AgentPackValidationError("path escapes allowed root", field=field) from exc
    # reject symlink in any existing component of target path
    cur = root_resolved
    for part in rp.parts:
        cur = cur / part
        if _lexists(cur) and cur.is_symlink():
            raise AgentPackValidationError("symlink escape rejected", field=field)
    return resolved


def _read_json_file(path: Path, *, field: str) -> Any:
    try:
        raw = path.read_bytes()
    except Exception as exc:
        raise AgentPackValidationError(f"cannot read {field}: {exc}", field=field) from exc
    if len(raw) > 2 * 1024 * 1024:
        raise AgentPackValidationError(f"{field} exceeds size limit", field=field)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise AgentPackValidationError(f"invalid JSON in {field}: {exc}", field=field) from exc


def _load_bundle_files(bundle_dir: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Path]]:
    bundle_manifest = _read_json_file(bundle_dir / "bundle.manifest.json", field="bundle.manifest.json")
    provenance = _read_json_file(bundle_dir / "provenance.json", field="provenance.json")
    loss_report = _read_json_file(bundle_dir / "capability-loss.report.json", field="capability-loss.report.json")
    if not isinstance(bundle_manifest, dict) or not isinstance(provenance, dict) or not isinstance(loss_report, dict):
        raise AgentPackValidationError("bundle metadata must be objects", field="bundle")
    files = bundle_manifest.get("files")
    if not isinstance(files, list):
        raise AgentPackValidationError("bundle.manifest.json files must be list", field="bundle.manifest.json.files")
    file_map: dict[str, Path] = {}
    for item in files:
        if not isinstance(item, dict):
            raise AgentPackValidationError("bundle file entry must be object", field="bundle.manifest.json.files")
        rel = item.get("path")
        if not isinstance(rel, str):
            raise AgentPackValidationError("bundle file path must be string", field="bundle.manifest.json.files.path")
        abs_path = _resolve_under_root(bundle_dir, rel, field=f"bundle:{rel}")
        if not abs_path.exists() or not abs_path.is_file():
            raise AgentPackValidationError("bundle file missing", field=rel)
        file_map[rel] = abs_path
    # manifest itself must exist but is not listed as file entry
    manifest_path = bundle_dir / "bundle.manifest.json"
    if not manifest_path.exists():
        raise AgentPackValidationError("bundle.manifest.json missing", field="bundle.manifest.json")
    return bundle_manifest, provenance, loss_report.get("items", []) if isinstance(loss_report.get("items"), list) else [], file_map


def _verify_bundle_hashes(bundle_dir: Path) -> tuple[bool, list[str], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Path]]:
    reasons: list[str] = []
    try:
        bundle_manifest, provenance, loss_items, file_map = _load_bundle_files(bundle_dir)
    except Exception as exc:
        return False, [str(exc)], {}, {}, [], {}

    files = bundle_manifest.get("files", [])
    normalized_files = []
    ok = True
    for item in files:
        rel = item.get("path")
        expected_sha = item.get("sha256")
        expected_bytes = item.get("bytes")
        abs_path = file_map.get(rel)
        if abs_path is None:
            ok = False
            reasons.append(f"missing file: {rel}")
            continue
        raw = abs_path.read_bytes()
        actual_sha = _sha256_bytes(raw)
        actual_bytes = len(raw)
        if actual_sha != expected_sha or actual_bytes != expected_bytes:
            ok = False
            reasons.append(f"hash mismatch: {rel}")
        normalized_files.append({"path": rel, "sha256": actual_sha, "bytes": actual_bytes})

    normalized_files = sorted(normalized_files, key=lambda x: x["path"])
    expected_bundle_sha = bundle_manifest.get("bundle_sha256")
    actual_bundle_sha = _sha256_json(normalized_files)
    if actual_bundle_sha != expected_bundle_sha:
        ok = False
        reasons.append("bundle_sha256 mismatch")

    prov_bundle_sha = provenance.get("bundle_sha256")
    content_sha = _content_bundle_sha256(bundle_manifest)
    if prov_bundle_sha not in {expected_bundle_sha, actual_bundle_sha, content_sha}:
        reasons.append("provenance bundle_sha256 does not match manifest/content")
    return ok, reasons, bundle_manifest, provenance, loss_items, file_map


def _has_capability_loss(loss_items: list[Any]) -> bool:
    if not loss_items:
        return False
    for item in loss_items:
        if not isinstance(item, dict):
            return True
        status = str(item.get("status", "")).lower()
        severity = str(item.get("severity", "")).lower()
        if status in {"partial", "unsupported", "transformed", "denied"}:
            return True
        if severity in {"warn", "blocker", "high"}:
            return True
    return True


def _get_signature_envelope(provenance: dict[str, Any]) -> dict[str, Any] | None:
    src = provenance.get("source_provenance")
    if not isinstance(src, dict):
        return None
    sig = src.get("signature")
    if sig is None:
        return None
    if isinstance(sig, dict):
        return sig
    # legacy/string signature: treat as unsigned/fail-closed, not crypto-verified.
    return {"__legacy__": str(sig)}


def _normalize_loaded_trusted_keys(trusted_keys: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if trusted_keys is None:
        return _load_trusted_public_keys()
    # Backward compat: callers may pass {kid: pem}.
    if all(isinstance(v, str) for v in trusted_keys.values()):
        return _normalize_trusted_keys_obj(trusted_keys, field="trusted_keys")
    out: dict[str, dict[str, Any]] = {}
    for k, v in trusted_keys.items():
        kid, rec = _normalize_trusted_key_record(v, field=f"trusted_keys.{k}", key_id=k if isinstance(k, str) else None)
        out[kid] = rec
    return out


def verify_bundle_signature(
    bundle_manifest: dict[str, Any],
    provenance: dict[str, Any],
    *,
    trusted_keys: dict[str, str] | dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    """Verify Ed25519 signature over deterministic bundle payload.

    Fail-closed: missing/invalid signature, unknown/revoked/expired/not-yet-valid key,
    bad encoding, or invalid signature returns (False, reasons, envelope).
    Local-only; no network, no shell.
    """
    reasons: list[str] = []
    now_dt = now.astimezone(timezone.utc) if isinstance(now, datetime) else datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    sig = _get_signature_envelope(provenance)
    if sig is None:
        return False, ["bundle unsigned or missing signature"], None

    meta: dict[str, Any] = {
        "key_id": sig.get("key_id") if isinstance(sig, dict) else None,
        "revoked": False,
        "expired": False,
        "not_yet_valid": False,
        "revocation_checked": False,
        "trusted_key_count": 0,
        "purpose": None,
    }

    def _ret(ok: bool, rs: list[str], envelope: dict[str, Any] | None) -> tuple[bool, list[str], dict[str, Any] | None]:
        if isinstance(envelope, dict):
            out = dict(envelope)
            out["_trust"] = meta
            return ok, rs, out
        return ok, rs, envelope

    if "__legacy__" in sig:
        return _ret(False, ["legacy/non-crypto signature metadata; fail closed"], sig)

    alg = sig.get("alg")
    key_id = sig.get("key_id")
    sig_b64 = sig.get("signature_b64")
    payload_sha = sig.get("payload_sha256")
    if alg != _SIGNATURE_ALG_ED25519:
        reasons.append(f"unsupported signature alg: {alg!r}")
    if not isinstance(key_id, str) or not key_id.strip():
        reasons.append("signature missing key_id")
    else:
        key_id = key_id.strip()
        meta["key_id"] = key_id
    if not isinstance(sig_b64, str) or not sig_b64:
        reasons.append("signature missing signature_b64")
    if not isinstance(payload_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", payload_sha.lower()):
        reasons.append("signature missing/invalid payload_sha256")
    if reasons:
        return _ret(False, reasons, sig)

    payload = _signature_payload(bundle_manifest, provenance)
    actual_payload_sha = _sha256_bytes(payload)
    if actual_payload_sha != payload_sha.lower():
        return _ret(False, ["signature payload_sha256 mismatch"], sig)

    try:
        keys = _normalize_loaded_trusted_keys(trusted_keys)
        revoked_keys = _load_revoked_keys()
    except AgentPackValidationError as exc:
        # Missing/bad local trust config is fail-closed but not signature tamper.
        return _ret(False, [str(exc)], sig)
    meta["trusted_key_count"] = len(keys)
    meta["revocation_checked"] = os.getenv(_REVOKED_KEYS_FILE_ENV, "").strip() != "" or any(bool(r.get("revoked")) for r in keys.values())
    if not keys:
        return _ret(False, ["no trusted keys configured; fail closed to unsigned"], sig)

    rec = keys.get(str(key_id))
    if rec is None:
        return _ret(False, [f"unknown signing key_id: {key_id}"], sig)
    meta["purpose"] = rec.get("purpose")

    if rec.get("purpose") not in (None, "agent_pack_bundle"):
        return _ret(False, [f"key purpose not allowed for agent_pack_bundle: {key_id}"], sig)
    if bool(rec.get("revoked")) or str(key_id) in revoked_keys:
        meta["revoked"] = True
        return _ret(False, [f"revoked signing key_id: {key_id}"], sig)
    nb = _parse_iso8601_utc(rec.get("not_before"), field="trusted_key.not_before") if rec.get("not_before") else None
    na = _parse_iso8601_utc(rec.get("not_after"), field="trusted_key.not_after") if rec.get("not_after") else None
    if nb and now_dt < nb:
        meta["not_yet_valid"] = True
        return _ret(False, [f"key not yet valid: {key_id}"], sig)
    if na and now_dt > na:
        meta["expired"] = True
        return _ret(False, [f"key expired: {key_id}"], sig)

    pem = rec.get("public_key_pem")
    try:
        pub = _load_pem_public_key(pem, field="trusted_keys.public_key_pem")
        raw_sig = _b64decode_str(sig_b64, field="signature.signature_b64")
        pub.verify(raw_sig, payload)
    except AgentPackValidationError as exc:
        return _ret(False, [str(exc)], sig)
    except Exception:
        # fail closed, no detail leak needed beyond invalid
        return _ret(False, ["invalid signature"], sig)

    # optional embedded public key must match trusted key for key_id; never trust embedded key alone.
    embedded_pem = sig.get("public_key_pem")
    if embedded_pem is not None:
        if not isinstance(embedded_pem, str) or not embedded_pem.strip():
            return _ret(False, ["invalid embedded public_key_pem"], sig)
        try:
            emb = _load_pem_public_key(embedded_pem, field="signature.public_key_pem")
            if _public_key_pem(emb).strip() != _public_key_pem(pub).strip():
                return _ret(False, ["embedded public_key_pem does not match trusted key"], sig)
        except AgentPackValidationError as exc:
            return _ret(False, [str(exc)], sig)

    return _ret(True, [], sig)


def _trust_meta_from_envelope(env: dict[str, Any] | None) -> dict[str, Any]:
    base = {"key_id": None, "revoked": False, "expired": False, "not_yet_valid": False, "revocation_checked": False, "trusted_key_count": 0, "purpose": None}
    if isinstance(env, dict) and isinstance(env.get("_trust"), dict):
        base.update({k: env["_trust"].get(k, base[k]) for k in base})
    return base


def _evaluate_trust(
    bundle_manifest: dict[str, Any],
    provenance: dict[str, Any],
    hashes_ok: bool,
    reasons: list[str],
    *,
    log_context: str,
) -> dict[str, Any]:
    trust_reasons = list(reasons)
    trust_meta = {"key_id": None, "revoked": False, "expired": False, "not_yet_valid": False, "revocation_checked": False, "trusted_key_count": 0, "purpose": None}
    if not hashes_ok:
        result = {
            "trust": "invalid",
            "trust_reasons": trust_reasons,
            "trust_meta": trust_meta,
            "signature_envelope": None,
        }
        _maybe_log_trust(result, bundle_manifest=bundle_manifest, context=log_context)
        return result

    sig = _get_signature_envelope(provenance)
    unsigned_flag = bool(bundle_manifest.get("unsigned", True)) or bool(provenance.get("unsigned", True))
    if sig is None:
        trust_reasons.append("bundle unsigned or missing signature")
        result = {"trust": "unsigned", "trust_reasons": trust_reasons, "trust_meta": trust_meta, "signature_envelope": None}
        _maybe_log_trust(result, bundle_manifest=bundle_manifest, context=log_context)
        return result

    ok, sig_reasons, env = verify_bundle_signature(bundle_manifest, provenance)
    trust_meta = _trust_meta_from_envelope(env)
    if not ok:
        trust_reasons.extend(sig_reasons)
        hard_invalid = any(
            r in {"invalid signature", "signature payload_sha256 mismatch"}
            or r.startswith("invalid ")
            or "mismatch" in r.lower()
            or "does not match" in r.lower()
            for r in sig_reasons
        )
        key_trust_invalid = bool(
            trust_meta.get("revoked")
            or trust_meta.get("expired")
            or trust_meta.get("not_yet_valid")
        ) or any(
            x in r.lower()
            for r in sig_reasons
            for x in ("revoked", "expired", "not yet valid", "purpose not allowed")
        )
        # Revoked/expired/not-yet-valid/invalid key metadata => invalid trust (fail-closed).
        # Unknown key/missing trusted config remain unsigned (fail-closed, not trusted).
        # Signature/content tamper => invalid.
        trust = "invalid" if (hard_invalid or key_trust_invalid) else "unsigned"
        result = {"trust": trust, "trust_reasons": trust_reasons, "trust_meta": trust_meta, "signature_envelope": env}
        _maybe_log_trust(result, bundle_manifest=bundle_manifest, context=log_context)
        return result

    if unsigned_flag:
        trust_reasons.append("signed bundle has unsigned metadata flag; treated as trusted due valid signature")
    if any("provenance bundle_sha256 does not match" in r for r in trust_reasons):
        trust_reasons = [r for r in trust_reasons if "provenance bundle_sha256 does not match" not in r]
    result = {"trust": "trusted", "trust_reasons": trust_reasons, "trust_meta": trust_meta, "signature_envelope": env}
    _maybe_log_trust(result, bundle_manifest=bundle_manifest, context=log_context)
    return result


def _maybe_log_trust(result: dict[str, Any], *, bundle_manifest: dict[str, Any], context: str) -> None:
    meta = result.get("trust_meta") or {}
    entry = {
        "ts": _now_iso(),
        "event": "agent_pack_trust",
        "context": context,
        "bundle_sha256": str(bundle_manifest.get("bundle_sha256") or ""),
        "fingerprint": str(bundle_manifest.get("source_pack_fingerprint") or ""),
        "trust": result.get("trust"),
        "trust_reasons": list(result.get("trust_reasons") or []),
        "key_id": meta.get("key_id"),
        "revoked": bool(meta.get("revoked")),
        "expired": bool(meta.get("expired")),
        "not_yet_valid": bool(meta.get("not_yet_valid")),
        "revocation_checked": bool(meta.get("revocation_checked")),
        "trusted_key_count": int(meta.get("trusted_key_count") or 0),
    }
    logged, err = _append_trust_log(entry)
    result["transparency_logged"] = logged
    result["transparency_log_error"] = err
    if err:
        # Best-effort: do not alter trust decision.
        result.setdefault("warnings", []).append(err)


def _verify_trust(bundle_manifest: dict[str, Any], provenance: dict[str, Any], hashes_ok: bool, reasons: list[str]) -> tuple[Literal["trusted", "unsigned", "invalid"], list[str]]:
    res = _evaluate_trust(bundle_manifest, provenance, hashes_ok, reasons, log_context="legacy")
    return res["trust"], res["trust_reasons"]


def inspect_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    bdir = Path(bundle_dir)
    if not bdir.exists() or not bdir.is_dir():
        raise AgentPackValidationError("bundle_dir must be an existing directory", field="bundle_dir")
    _reject_symlink_path(bdir.resolve(), "bundle_dir")
    hashes_ok, reasons, bundle_manifest, provenance, loss_items, _ = _verify_bundle_hashes(bdir.resolve())
    trust_res = _evaluate_trust(bundle_manifest, provenance, hashes_ok, reasons, log_context="inspect")
    meta = trust_res.get("trust_meta") or {}
    return {
        "bundle_dir": str(bdir.resolve()),
        "bundle_hash": str(bundle_manifest.get("bundle_sha256") or ""),
        "hashes_ok": hashes_ok,
        "trust": trust_res["trust"],
        "trust_reasons": trust_res["trust_reasons"],
        "key_id": meta.get("key_id"),
        "revocation_checked": bool(meta.get("revocation_checked")),
        "trusted_key_count": int(meta.get("trusted_key_count") or 0),
        "transparency_logged": bool(trust_res.get("transparency_logged")),
        "provenance_present": bool(provenance),
        "capability_loss": loss_items,
        "manifest": bundle_manifest,
        "provenance": provenance,
        "warnings": list(trust_res.get("warnings") or []),
    }


def _target_root_for(target: InstallTarget, target_root: str | Path | None) -> Path:
    if target not in _TARGETS:
        raise AgentPackValidationError(f"unknown install target: {target}", field="target")
    root = Path(target_root) if target_root is not None else _DEFAULT_TARGET_ROOTS[target]
    root = root.expanduser()
    if not root.is_absolute():
        root = root.resolve()
    else:
        root = root.resolve()
    # must not be symlink
    if _lexists(root) and root.is_symlink():
        raise AgentPackValidationError("target_root must not be symlink", field="target_root")
    return root


def _installable_files(bundle_manifest: dict[str, Any], bundle_dir: Path, file_map: dict[str, Path]) -> list[tuple[str, Path]]:
    files = bundle_manifest.get("files", [])
    out = []
    for item in sorted(files, key=lambda x: x.get("path", "")):
        rel = item["path"]
        # metadata files are inspected, not installed into runtime target
        if rel in {"bundle.manifest.json", "provenance.json", "capability-loss.report.json", "agent-pack.canonical.json"}:
            continue
        out.append((rel, file_map[rel]))
    return out


def _plan_hash_payload(plan: dict[str, Any]) -> str:
    copy = dict(plan)
    copy.pop("plan_hash", None)
    return _sha256_json(copy)


def plan_install(
    bundle_dir: str | Path,
    target: InstallTarget,
    *,
    target_root: str | Path | None = None,
    records_dir: str | Path | None = None,
) -> InstallPlan:
    bdir = Path(bundle_dir).resolve()
    inspection = inspect_bundle(bdir)
    if inspection["trust"] == "invalid":
        raise AgentPackValidationError("; ".join(inspection["trust_reasons"]) or "invalid bundle", field="bundle")

    bundle_manifest, provenance, loss_items, file_map = _load_bundle_files(bdir)
    root = _target_root_for(target, target_root)
    records_root = Path(records_dir).expanduser().resolve() if records_dir is not None else _DEFAULT_RECORD_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    records_root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or records_root.is_symlink():
        raise AgentPackValidationError("target/records root must not be symlink", field="target_root")

    ops: list[PlannedOperation] = []
    installable = _installable_files(bundle_manifest, bdir, file_map)
    bundle_hash = str(bundle_manifest.get("bundle_sha256"))
    for rel, src_path in installable:
        dst = _resolve_under_root(root, rel, field=f"target:{rel}")
        src_raw = src_path.read_bytes()
        after_hash = _sha256_bytes(src_raw)
        if dst.exists():
            if dst.is_dir():
                raise AgentPackValidationError("target path is directory", field=rel)
            if dst.is_symlink():
                raise AgentPackValidationError("target path symlink rejected", field=rel)
            before_raw = dst.read_bytes()
            before_hash = _sha256_bytes(before_raw)
            if before_hash == after_hash:
                op = "noop"
                reason = "unchanged"
                backup_path = None
            else:
                op = "modify"
                reason = "content differs"
                backup_path = str((records_root / "backups" / bundle_hash / rel).resolve())
        else:
            op = "create"
            reason = "new file"
            before_hash = None
            backup_path = None
        ops.append(PlannedOperation(
            op=op,
            rel_path=rel,
            abs_path=str(dst),
            before_hash=before_hash,
            after_hash=after_hash,
            backup_path=backup_path,
            reason=reason,
        ))

    commands_preview = [
        f"inspect bundle: {bdir}",
        f"install target={target} root={root}",
        f"apply {sum(1 for o in ops if o.op != 'noop')} file operation(s) with explicit consent",
    ]
    rollback_plan = {
        "strategy": "restore backups for modified files and remove created files in reverse order",
        "record_dir": str(records_root),
    }
    requires_capability_loss_ack = _has_capability_loss(loss_items)
    requires_unsigned_ack = inspection["trust"] == "unsigned"
    plan_payload = {
        "bundle_dir": str(bdir),
        "bundle_hash": bundle_hash,
        "target": target,
        "target_root": str(root),
        "trust": inspection["trust"],
        "trust_reasons": inspection["trust_reasons"],
        "capability_loss": loss_items,
        "operations": [o.model_dump(mode="json") for o in ops],
        "commands_preview": commands_preview,
        "rollback_plan": rollback_plan,
        "requires_capability_loss_ack": requires_capability_loss_ack,
        "requires_unsigned_ack": requires_unsigned_ack,
    }
    plan_payload["plan_hash"] = _plan_hash_payload(plan_payload)
    return InstallPlan.model_validate(plan_payload)


def _ensure_consent(plan: InstallPlan, consent: InstallConsent) -> list[str]:
    errors: list[str] = []
    if consent.actor.strip() == "":
        errors.append("actor required")
    if consent.bundle_hash != plan.bundle_hash:
        errors.append("bundle_hash mismatch")
    if consent.target != plan.target:
        errors.append("target mismatch")
    if consent.plan_hash != plan.plan_hash:
        errors.append("plan_hash mismatch")
    if plan.requires_capability_loss_ack and not consent.capability_loss_ack:
        errors.append("capability_loss_ack required")
    if plan.trust == "invalid":
        errors.append("invalid bundle cannot be installed")
    if plan.trust == "unsigned":
        if not consent.allow_unsigned:
            errors.append("unsigned bundle requires allow_unsigned")
        if "UNSIGNED_RISK_ACCEPTED" not in consent.consent_phrase:
            errors.append("unsigned bundle requires consent_phrase containing UNSIGNED_RISK_ACCEPTED")
    if not consent.consent_phrase.strip():
        errors.append("consent_phrase required")
    # basic timestamp presence/parse
    try:
        datetime.fromisoformat(consent.timestamp.replace("Z", "+00:00"))
    except Exception:
        errors.append("timestamp invalid")
    return errors


def _audit_record_path(records_dir: Path) -> Path:
    return records_dir / "audit.jsonl"


def _write_audit(records_dir: Path, record: dict[str, Any]) -> Path:
    records_dir.mkdir(parents=True, exist_ok=True)
    path = _audit_record_path(records_dir)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return path


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".pkg")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
        # fsync dir best effort
        try:
            dfd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except Exception:
            pass
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass


def _backup_file(src: Path, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    raw = src.read_bytes()
    _atomic_write(backup_path, raw)


def _install_record_dir(records_dir: Path) -> Path:
    d = records_dir / "records"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_install_record(records_dir: Path, record: dict[str, Any]) -> Path:
    rec_dir = _install_record_dir(records_dir)
    name = f"{_safe_id_fragment(record.get('timestamp',''))}-{_safe_id_fragment(record.get('bundle_hash',''))[:12]}-{_safe_id_fragment(record.get('target',''))}.json"
    path = rec_dir / name
    _atomic_write(path, (_canonical_json(record) + "\n").encode("utf-8"))
    return path


def _load_install_record(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = _read_json_file(p, field="install_record")
    if not isinstance(data, dict):
        raise AgentPackValidationError("install record must be object", field="install_record")
    return data


def _rollback_applied(applied: list[dict[str, Any]], *, target_root: Path) -> list[str]:
    errors: list[str] = []
    for item in reversed(applied):
        op = item.get("op")
        rel = item.get("rel_path")
        try:
            dst = _resolve_under_root(target_root, rel, field=f"rollback:{rel}")
            if op == "create":
                if dst.exists():
                    dst.unlink()
            elif op == "modify":
                backup = item.get("backup_path")
                if not backup:
                    errors.append(f"missing backup for {rel}")
                    continue
                bpath = Path(backup)
                raw = bpath.read_bytes()
                _atomic_write(dst, raw)
            # noop: nothing
        except Exception as exc:
            errors.append(f"rollback failed for {rel}: {exc}")
    return errors


def _target_root_allowed(target_root: Path, records_dir: Path) -> None:
    # No writes outside target root and records dir: enforced by explicit root resolution and record paths.
    if (_lexists(target_root) and target_root.is_symlink()) or (_lexists(records_dir) and records_dir.is_symlink()):
        raise AgentPackValidationError("symlink root rejected", field="target_root")


def apply_install(
    plan: InstallPlan | dict[str, Any],
    *,
    consent: InstallConsent | dict[str, Any],
    records_dir: str | Path | None = None,
    audit_log_path: str | Path | None = None,
) -> InstallResult:
    plan_obj = plan if isinstance(plan, InstallPlan) else InstallPlan.model_validate(plan)
    consent_obj = consent if isinstance(consent, InstallConsent) else InstallConsent.model_validate(consent)
    records_root = Path(records_dir).expanduser().resolve() if records_dir is not None else _DEFAULT_RECORD_DIR.resolve()
    audit_path = Path(audit_log_path).expanduser().resolve() if audit_log_path is not None else _audit_record_path(records_root)
    records_root.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    warnings: list[str] = []
    applied: list[dict[str, Any]] = []
    rolled_back = False

    # Recompute plan hash and verify unchanged
    plan_payload = plan_obj.model_dump(mode="json")
    expected_hash = plan_payload.get("plan_hash")
    actual_hash = _plan_hash_payload(plan_payload)
    if expected_hash != actual_hash:
        errors.append("plan_hash recompute mismatch")
    if expected_hash != consent_obj.plan_hash:
        errors.append("consent plan_hash mismatch")

    consent_errors = _ensure_consent(plan_obj, consent_obj)
    errors.extend(consent_errors)

    # Re-inspect bundle for tamper/trust at apply time
    try:
        inspection = inspect_bundle(plan_obj.bundle_dir)
    except Exception as exc:
        inspection = {"trust": "invalid", "trust_reasons": [str(exc)], "bundle_hash": "", "warnings": []}
    if inspection.get("bundle_hash") != plan_obj.bundle_hash:
        errors.append("bundle hash changed since planning")
    if inspection.get("trust") == "invalid":
        errors.append("bundle invalid/tampered")
    if inspection.get("trust") == "unsigned" and plan_obj.trust != "unsigned":
        errors.append("bundle trust downgraded")
    if plan_obj.trust == "unsigned":
        warnings.append("UNSIGNED bundle install explicitly consented; verify provenance before use")
    for w in inspection.get("warnings") or []:
        if w not in warnings:
            warnings.append(w)
    # Apply-time transparency log entry (best-effort, no trust impact).
    try:
        hashes_ok, reasons, bundle_manifest, provenance, _, _ = _verify_bundle_hashes(Path(plan_obj.bundle_dir).resolve())
        trust_res = _evaluate_trust(bundle_manifest, provenance, hashes_ok, reasons, log_context="install")
        for w in trust_res.get("warnings") or []:
            if w not in warnings:
                warnings.append(w)
    except Exception as exc:
        warnings.append(f"trust log evaluation failed: {exc}")

    target_root = Path(plan_obj.target_root).resolve()
    _target_root_allowed(target_root, records_root)
    if not target_root.is_relative_to(Path(target_root.anchor)) :
        pass

    install_record_path: Path | None = None
    if errors:
        result = InstallResult(
            ok=False, target=plan_obj.target, bundle_hash=plan_obj.bundle_hash, plan_hash=plan_obj.plan_hash,
            install_record_path=None, audit_log_path=str(audit_path), applied=[], rolled_back=False,
            warnings=warnings, errors=errors,
        )
        _write_audit(audit_path.parent, {
            "ts": _now_iso(), "event": "agent_pack_install.apply", "ok": False,
            "target": plan_obj.target, "bundle_hash": plan_obj.bundle_hash, "plan_hash": plan_obj.plan_hash,
            "actor": consent_obj.actor, "errors": errors, "warnings": warnings,
        })
        return result

    # Load bundle source files
    bdir = Path(plan_obj.bundle_dir).resolve()
    bundle_manifest, _, _, file_map = _load_bundle_files(bdir)

    try:
        for op in plan_obj.operations:
            if op.op == "noop":
                applied.append({"op": "noop", "rel_path": op.rel_path, "abs_path": op.abs_path})
                continue
            dst = _resolve_under_root(target_root, op.rel_path, field=f"apply:{op.rel_path}")
            src = file_map.get(op.rel_path)
            if src is None:
                raise AgentPackValidationError("planned source missing from bundle", field=op.rel_path)
            raw = src.read_bytes()
            if _sha256_bytes(raw) != op.after_hash:
                raise AgentPackValidationError("source hash changed before apply", field=op.rel_path)
            if op.op == "modify":
                if not dst.exists():
                    raise AgentPackValidationError("expected existing file for modify", field=op.rel_path)
                backup_path = Path(op.backup_path) if op.backup_path else (records_root / "backups" / plan_obj.bundle_hash / op.rel_path)
                # backup must be under records_root
                backup_resolved = backup_path.resolve()
                if not backup_resolved.is_relative_to(records_root.resolve()):
                    raise AgentPackValidationError("backup path escapes records dir", field=op.rel_path)
                _backup_file(dst, backup_resolved)
                _atomic_write(dst, raw)
                applied.append({"op": "modify", "rel_path": op.rel_path, "abs_path": str(dst), "backup_path": str(backup_resolved), "before_hash": op.before_hash, "after_hash": op.after_hash})
            elif op.op == "create":
                if dst.exists():
                    raise AgentPackValidationError("target exists for create op", field=op.rel_path)
                _atomic_write(dst, raw)
                applied.append({"op": "create", "rel_path": op.rel_path, "abs_path": str(dst), "before_hash": None, "after_hash": op.after_hash})
            else:
                raise AgentPackValidationError(f"unknown op {op.op}", field=op.rel_path)
    except Exception as exc:
        errors.append(str(exc))
        rb_errors = _rollback_applied(applied, target_root=target_root)
        rolled_back = True
        if rb_errors:
            errors.extend(rb_errors)
        result = InstallResult(
            ok=False, target=plan_obj.target, bundle_hash=plan_obj.bundle_hash, plan_hash=plan_obj.plan_hash,
            install_record_path=None, audit_log_path=str(audit_path), applied=applied, rolled_back=rolled_back,
            warnings=warnings, errors=errors,
        )
        _write_audit(audit_path.parent, {
            "ts": _now_iso(), "event": "agent_pack_install.apply", "ok": False,
            "target": plan_obj.target, "bundle_hash": plan_obj.bundle_hash, "plan_hash": plan_obj.plan_hash,
            "actor": consent_obj.actor, "errors": errors, "warnings": warnings, "rolled_back": rolled_back,
        })
        return result

    record = {
        "schema_version": "1.0.0",
        "timestamp": _now_iso(),
        "event": "agent_pack_install.apply",
        "actor": consent_obj.actor,
        "target": plan_obj.target,
        "target_root": str(target_root),
        "bundle_dir": str(bdir),
        "bundle_hash": plan_obj.bundle_hash,
        "plan_hash": plan_obj.plan_hash,
        "trust": plan_obj.trust,
        "capability_loss_ack": consent_obj.capability_loss_ack,
        "consent_phrase": consent_obj.consent_phrase,
        "operations": applied,
        "rolled_back": False,
        "status": "applied",
    }
    install_record_path = _write_install_record(records_root, record)
    _write_audit(audit_path.parent, {
        "ts": record["timestamp"], "event": "agent_pack_install.apply", "ok": True,
        "target": plan_obj.target, "bundle_hash": plan_obj.bundle_hash, "plan_hash": plan_obj.plan_hash,
        "actor": consent_obj.actor, "install_record_path": str(install_record_path), "warnings": warnings,
    })
    return InstallResult(
        ok=True, target=plan_obj.target, bundle_hash=plan_obj.bundle_hash, plan_hash=plan_obj.plan_hash,
        install_record_path=str(install_record_path), audit_log_path=str(audit_path),
        applied=applied, rolled_back=False, warnings=warnings, errors=[],
    )


def _verify_record_consent(record: dict[str, Any], consent: InstallConsent, *, action: str) -> list[str]:
    errors: list[str] = []
    if consent.bundle_hash != record.get("bundle_hash"):
        errors.append("bundle_hash mismatch")
    if consent.target != record.get("target"):
        errors.append("target mismatch")
    if consent.plan_hash != record.get("plan_hash"):
        errors.append("plan_hash mismatch")
    if not consent.capability_loss_ack and record.get("capability_loss_ack"):
        errors.append("capability_loss_ack required")
    if not consent.consent_phrase.strip():
        errors.append("consent_phrase required")
    token = action.upper()
    if action in {"rollback", "uninstall"} and token not in consent.consent_phrase:
        errors.append(f"consent_phrase must include {token}")
    try:
        datetime.fromisoformat(consent.timestamp.replace("Z", "+00:00"))
    except Exception:
        errors.append("timestamp invalid")
    return errors


def _detect_drift(record: dict[str, Any]) -> list[str]:
    drifts: list[str] = []
    target_root = Path(record.get("target_root", ""))
    for op in record.get("operations", []):
        if op.get("op") == "noop":
            continue
        rel = op.get("rel_path")
        try:
            dst = _resolve_under_root(target_root, rel, field=f"drift:{rel}")
        except Exception as exc:
            drifts.append(f"{rel}: {exc}")
            continue
        if op.get("op") == "create":
            if not dst.exists():
                drifts.append(f"{rel}: missing created file")
                continue
            actual = _sha256_bytes(dst.read_bytes())
            if actual != op.get("after_hash"):
                drifts.append(f"{rel}: created file drifted")
        elif op.get("op") == "modify":
            if not dst.exists():
                drifts.append(f"{rel}: missing modified file")
                continue
            actual = _sha256_bytes(dst.read_bytes())
            if actual != op.get("after_hash"):
                drifts.append(f"{rel}: modified file drifted")
    return drifts


def rollback_install(
    install_record_path: str | Path,
    *,
    consent: InstallConsent | dict[str, Any],
    records_dir: str | Path | None = None,
    audit_log_path: str | Path | None = None,
) -> InstallResult:
    consent_obj = consent if isinstance(consent, InstallConsent) else InstallConsent.model_validate(consent)
    record = _load_install_record(install_record_path)
    records_root = Path(records_dir).expanduser().resolve() if records_dir is not None else _DEFAULT_RECORD_DIR.resolve()
    audit_path = Path(audit_log_path).expanduser().resolve() if audit_log_path is not None else _audit_record_path(records_root)
    errors = _verify_record_consent(record, consent_obj, action="rollback")
    warnings: list[str] = []
    drifts = _detect_drift(record)
    if drifts and not consent_obj.force:
        errors.append("drift detected; explicit force+consent required")
        warnings.extend(drifts)
    if drifts and consent_obj.force:
        warnings.append("drift detected but force consent provided")

    target_root = Path(record.get("target_root", "")).resolve()
    applied: list[dict[str, Any]] = []
    rolled_back = False
    if errors:
        _write_audit(audit_path.parent, {
            "ts": _now_iso(), "event": "agent_pack_install.rollback", "ok": False,
            "target": record.get("target"), "bundle_hash": record.get("bundle_hash"), "plan_hash": record.get("plan_hash"),
            "actor": consent_obj.actor, "errors": errors, "warnings": warnings,
        })
        return InstallResult(ok=False, target=record.get("target", "claude_code"), bundle_hash=str(record.get("bundle_hash", "")), plan_hash=str(record.get("plan_hash", "")), install_record_path=str(install_record_path), audit_log_path=str(audit_path), applied=[], rolled_back=False, warnings=warnings, errors=errors)

    rb_errors = _rollback_applied(record.get("operations", []), target_root=target_root)
    rolled_back = len(rb_errors) == 0
    if rb_errors:
        errors.extend(rb_errors)
    rec2 = dict(record)
    rec2["status"] = "rolled_back" if rolled_back else "rollback_failed"
    rec2["rolled_back_at"] = _now_iso()
    rec2["rolled_back_by"] = consent_obj.actor
    _atomic_write(Path(install_record_path).resolve(), (_canonical_json(rec2) + "\n").encode("utf-8"))
    _write_audit(audit_path.parent, {
        "ts": _now_iso(), "event": "agent_pack_install.rollback", "ok": rolled_back,
        "target": record.get("target"), "bundle_hash": record.get("bundle_hash"), "plan_hash": record.get("plan_hash"),
        "actor": consent_obj.actor, "errors": errors, "warnings": warnings,
    })
    return InstallResult(ok=rolled_back, target=record.get("target"), bundle_hash=str(record.get("bundle_hash")), plan_hash=str(record.get("plan_hash")), install_record_path=str(install_record_path), audit_log_path=str(audit_path), applied=applied, rolled_back=rolled_back, warnings=warnings, errors=errors)


def uninstall(
    install_record_path: str | Path,
    *,
    consent: InstallConsent | dict[str, Any],
    records_dir: str | Path | None = None,
    audit_log_path: str | Path | None = None,
) -> InstallResult:
    # uninstall == rollback semantics for this guided local installer
    consent_obj = consent if isinstance(consent, InstallConsent) else InstallConsent.model_validate(consent)
    # require UNINSTALL token; reuse rollback but preserve action message
    errors = []
    if "UNINSTALL" not in consent_obj.consent_phrase:
        # let rollback add its token? easier: create a modified consent not possible (frozen). validate directly.
        pass
    record = _load_install_record(install_record_path)
    records_root = Path(records_dir).expanduser().resolve() if records_dir is not None else _DEFAULT_RECORD_DIR.resolve()
    audit_path = Path(audit_log_path).expanduser().resolve() if audit_log_path is not None else _audit_record_path(records_root)
    base_errors = _verify_record_consent(record, consent_obj, action="uninstall")
    warnings: list[str] = []
    drifts = _detect_drift(record)
    if drifts and not consent_obj.force:
        base_errors.append("drift detected; explicit force+consent required")
        warnings.extend(drifts)
    if base_errors:
        _write_audit(audit_path.parent, {
            "ts": _now_iso(), "event": "agent_pack_install.uninstall", "ok": False,
            "target": record.get("target"), "bundle_hash": record.get("bundle_hash"), "plan_hash": record.get("plan_hash"),
            "actor": consent_obj.actor, "errors": base_errors, "warnings": warnings,
        })
        return InstallResult(ok=False, target=record.get("target", "claude_code"), bundle_hash=str(record.get("bundle_hash", "")), plan_hash=str(record.get("plan_hash", "")), install_record_path=str(install_record_path), audit_log_path=str(audit_path), applied=[], rolled_back=False, warnings=warnings, errors=base_errors)
    target_root = Path(record.get("target_root", "")).resolve()
    rb_errors = _rollback_applied(record.get("operations", []), target_root=target_root)
    ok = len(rb_errors) == 0
    rec2 = dict(record)
    rec2["status"] = "uninstalled" if ok else "uninstall_failed"
    rec2["uninstalled_at"] = _now_iso()
    rec2["uninstalled_by"] = consent_obj.actor
    _atomic_write(Path(install_record_path).resolve(), (_canonical_json(rec2) + "\n").encode("utf-8"))
    _write_audit(audit_path.parent, {
        "ts": _now_iso(), "event": "agent_pack_install.uninstall", "ok": ok,
        "target": record.get("target"), "bundle_hash": record.get("bundle_hash"), "plan_hash": record.get("plan_hash"),
        "actor": consent_obj.actor, "errors": rb_errors, "warnings": warnings,
    })
    return InstallResult(ok=ok, target=record.get("target"), bundle_hash=str(record.get("bundle_hash")), plan_hash=str(record.get("plan_hash")), install_record_path=str(install_record_path), audit_log_path=str(audit_path), applied=[], rolled_back=ok, warnings=warnings, errors=rb_errors)


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="aios.core.agent_pack_install")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("inspect")
    pi.add_argument("bundle_dir")
    pp = sub.add_parser("plan")
    pp.add_argument("bundle_dir")
    pp.add_argument("--target", required=True, choices=list(_TARGETS))
    pp.add_argument("--target-root")
    pp.add_argument("--records-dir")
    args = p.parse_args(argv)
    if args.cmd == "inspect":
        print(_canonical_json(inspect_bundle(args.bundle_dir)))
        return 0
    if args.cmd == "plan":
        plan = plan_install(args.bundle_dir, args.target, target_root=args.target_root, records_dir=args.records_dir)
        print(_canonical_json(plan.model_dump(mode="json")))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
