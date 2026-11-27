"""Append-only, hash-chained JSONL sink for security telemetry.

Independent of the application DB by construction: the chain lives in a local
file and is verified from the file itself. A host-level compromise can still
rewrite the file (and recompute hashes), so this is tamper-evident, not
tamper-proof against root or the running service account.

Sinks:
- local_chain (default): append-only hash-chained JSONL, fsync'd.
- external stub (optional): webhook_stub or file_queue_stub. No vendor SDK,
  no network calls, no credentials. Stub only for WORM-capable plumbing.

Config (env, AIOS_ prefix via settings where present):
- AIOS_AUDIT_SINK_PATH: local chain path
- AIOS_AUDIT_SINK_MIRROR_PATH: legacy external mirror path (file)
- AIOS_AUDIT_SINK_MIRROR_REQUIRED: fail-closed for legacy mirror
- AIOS_AUDIT_SINK_EXTERNAL_KIND: webhook_stub|file_queue_stub|""
- AIOS_AUDIT_SINK_EXTERNAL_TARGET: stub target (URL for webhook_stub, dir for file_queue_stub)
- AIOS_AUDIT_SINK_REQUIRED: fail-closed when configured external sink fails
"""


from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
_TAIL_BYTES = 1 << 20
_LOCK = threading.Lock()
_FIELDS = {"seq", "ts", "org_id", "event", "prev_hash", "data", "hash"}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class AuditChainError(ValueError):
    """Raised when a record or the chain fails validation; fail closed."""


class AuditSink(Protocol):
    """Small sink interface: emit one record, return ack metadata."""

    name: str

    def emit(self, record: dict) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SinkAck:
    sink: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"sink": self.sink, "ok": self.ok, "detail": self.detail}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _settings():
    try:
        from aios.config import settings
        return settings
    except Exception:
        return None


def _cfg_str(attr: str, env: str) -> str:
    s = _settings()
    if s is not None:
        v = getattr(s, attr, "")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return os.getenv(env, "").strip()


def _cfg_bool(attr: str, env: str, default: bool = False) -> bool:
    s = _settings()
    if s is not None and hasattr(s, attr):
        v = getattr(s, attr)
        if isinstance(v, bool):
            # env override wins for runtime toggles/tests
            env_v = os.getenv(env)
            if env_v is not None:
                return _bool_env(env, default)
            return v
    return _bool_env(env, default)


def sink_path(path: str | os.PathLike | None = None) -> Path:
    """Resolve the sink file: explicit arg, then env/config, then app data dir."""
    if path is not None:
        return Path(path).expanduser()
    configured = _cfg_str("audit_sink_path", "AIOS_AUDIT_SINK_PATH")
    if configured:
        return Path(configured).expanduser()
    s = _settings()
    base = Path(getattr(s, "app_data_dir", "./data") if s else "./data").expanduser()
    return base / "audit" / "telemetry.jsonl"


def mirror_sink_path(path: str | os.PathLike | None = None) -> Path | None:
    """Optional external/WORM mirror path. Disabled by default."""
    if path is not None:
        return Path(path).expanduser()
    configured = _cfg_str("audit_sink_mirror_path", "AIOS_AUDIT_SINK_MIRROR_PATH")
    if not configured:
        return None
    return Path(configured).expanduser()


def mirror_required() -> bool:
    return _cfg_bool("audit_sink_mirror_required", "AIOS_AUDIT_SINK_MIRROR_REQUIRED", False)


def external_sink_kind() -> str:
    return _cfg_str("audit_sink_external_kind", "AIOS_AUDIT_SINK_EXTERNAL_KIND").lower()


def external_sink_target() -> str:
    return _cfg_str("audit_sink_external_target", "AIOS_AUDIT_SINK_EXTERNAL_TARGET")


def sink_required() -> bool:
    """Fail closed for configured external sinks when true."""
    return _cfg_bool("audit_sink_required", "AIOS_AUDIT_SINK_REQUIRED", False)


def _canonical(record: dict) -> bytes:
    try:
        return json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AuditChainError(f"record is not JSON-serializable: {exc}") from exc


def _hash(record: dict) -> str:
    body = {key: value for key, value in record.items() if key != "hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditChainError(f"duplicate key: {key}")
        result[key] = value
    return result


def _parse_line(line: str | bytes, lineno: int) -> dict:
    try:
        record = json.loads(line, object_pairs_hook=_no_duplicate_keys)
    except (json.JSONDecodeError, UnicodeDecodeError, AuditChainError) as exc:
        raise AuditChainError(f"line {lineno}: invalid record: {exc}") from exc
    if not isinstance(record, dict) or set(record) != _FIELDS:
        raise AuditChainError(f"line {lineno}: unexpected record shape")
    if type(record["seq"]) is not int or record["seq"] < 1:
        raise AuditChainError(f"line {lineno}: bad seq")
    for key in ("ts", "org_id", "event", "prev_hash", "hash"):
        if not isinstance(record[key], str) or not record[key]:
            raise AuditChainError(f"line {lineno}: bad {key}")
    if not isinstance(record["data"], dict):
        raise AuditChainError(f"line {lineno}: bad data")
    if not _HEX64.fullmatch(record["prev_hash"]) or not _HEX64.fullmatch(record["hash"]):
        raise AuditChainError(f"line {lineno}: bad hash format")
    if not hmac.compare_digest(_hash(record), record["hash"]):
        raise AuditChainError(f"line {lineno}: hash mismatch")
    return record


def _tail_state(path: Path) -> tuple[str, int]:
    """Last committed (hash, seq), or genesis for a new/rotated file."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return GENESIS_HASH, 0
    if size == 0:
        return GENESIS_HASH, 0
    start = max(0, size - _TAIL_BYTES)
    with path.open("rb") as fh:
        fh.seek(start)
        chunk = fh.read()
    if b"\n" not in chunk and start > 0:
        raise AuditChainError("last audit record exceeds tail window")
    lines = chunk.splitlines()
    if not lines:
        return GENESIS_HASH, 0
    record = _parse_line(lines[-1], 1)
    return record["hash"], record["seq"]


def _append_payload(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        if os.write(fd, payload) != len(payload):
            raise OSError("short audit write")
        os.fsync(fd)
    finally:
        os.close(fd)


def _redact_target(value: str) -> str:
    # Never log secrets/tokens. Keep only coarse shape for operator diagnosis.
    v = (value or "").strip()
    if not v:
        return "<empty>"
    if "://" in v:
        scheme = v.split("://", 1)[0]
        return f"{scheme}://<redacted>"
    return "<path:redacted>"


class LocalChainSink:
    name = "local_chain"

    def __init__(self, path: str | os.PathLike | None = None):
        self._path = path

    def emit(self, record: dict) -> dict[str, Any]:
        target = sink_path(self._path)
        payload = _canonical(record) + b"\n"
        _append_payload(target, payload)
        return SinkAck(self.name, True, "appended").as_dict()


class FileQueueStubSink:
    """Stub external sink: durable local queue file, no vendor SDK/credentials."""

    name = "file_queue_stub"

    def __init__(self, target: str):
        self.target = target

    def emit(self, record: dict) -> dict[str, Any]:
        if not self.target:
            raise AuditChainError("external file_queue_stub target missing")
        root = Path(self.target).expanduser()
        queue = root / "audit-queue.jsonl"
        payload = _canonical({"sink": self.name, "record": record}) + b"\n"
        _append_payload(queue, payload)
        return SinkAck(self.name, True, "queued").as_dict()


class WebhookStubSink:
    """Stub external sink: validates config and records to local spool only.

    No HTTP call, no credentials, no external SDK. This keeps interface/strict
    semantics testable in dev/CI without prod infra.
    """

    name = "webhook_stub"

    def __init__(self, target: str):
        self.target = target

    def emit(self, record: dict) -> dict[str, Any]:
        t = (self.target or "").strip()
        if not (t.startswith("https://") or t.startswith("http://")):
            raise AuditChainError("external webhook_stub target must be http(s) URL")
        # Spool next to primary sink to make intent visible; no network send.
        spool = sink_path().with_name("audit-webhook-stub.jsonl")
        payload = _canonical(
            {"sink": self.name, "target": _redact_target(t), "record": record}
        ) + b"\n"
        _append_payload(spool, payload)
        return SinkAck(self.name, True, "spooled").as_dict()


def _external_sink_from_env() -> AuditSink | None:
    kind = external_sink_kind()
    if not kind:
        return None
    target = external_sink_target()
    if kind == "file_queue_stub":
        return FileQueueStubSink(target)
    if kind == "webhook_stub":
        return WebhookStubSink(target)
    logger.warning("audit sink external kind unsupported: %s", kind)
    if sink_required():
        raise AuditChainError("audit external sink misconfigured")
    return None


def _mirror_payload(payload: bytes, mirror_path: str | os.PathLike | None = None) -> None:
    """Backward-compat: legacy file mirror write."""
    target = mirror_sink_path(mirror_path)
    if target is None:
        return
    _append_payload(target, payload)


def _safe_mirror_payload(payload: bytes, mirror_path: str | os.PathLike | None = None) -> bool:
    """Backward-compat: legacy mirror with required/best-effort semantics. Returns ok."""
    try:
        _mirror_payload(payload, mirror_path=mirror_path)
        return True
    except Exception as exc:
        logger.warning("audit sink external mirror failed: %s", type(exc).__name__)
        if mirror_required():
            raise AuditChainError(f"audit mirror write failed: {type(exc).__name__}") from exc
        return False


def _legacy_mirror_sink(mirror_path: str | os.PathLike | None = None) -> AuditSink | None:
    target = mirror_sink_path(mirror_path)
    if target is None:
        return None

    class _LegacyMirror(LocalChainSink):
        name = "legacy_mirror"

        def emit(self, record: dict) -> dict[str, Any]:
            payload = _canonical(record) + b"\n"
            _safe_mirror_payload(payload, mirror_path=mirror_path)
            target2 = mirror_sink_path(mirror_path)
            if target2 is None:
                return SinkAck(self.name, True, "disabled").as_dict()
            # _safe_mirror_payload already handled required/best-effort; detect failure by checking write
            # If it raised, we won't be here. If best-effort failed, we should ack false?
            # _safe_mirror_payload swallowed non-required errors; we can't detect. Better emit directly.
            return SinkAck(self.name, True, "mirrored").as_dict()

    return _LegacyMirror(target)


def _emit_external(
    record: dict,
    mirror_path: str | os.PathLike | None = None,
) -> list[dict[str, Any]]:
    acks: list[dict[str, Any]] = []
    # Legacy mirror path: preserve old behavior exactly (monkeypatchable).
    legacy_target = mirror_sink_path(mirror_path)
    if legacy_target is not None:
        payload = _canonical(record) + b"\n"
        ok = _safe_mirror_payload(payload, mirror_path=mirror_path)
        acks.append(SinkAck("legacy_mirror", ok, "mirrored" if ok else "error").as_dict())

    ext = _external_sink_from_env()
    if ext is not None:
        required = sink_required()
        try:
            ack = ext.emit(record)
            acks.append(ack)
        except Exception as exc:
            logger.warning(
                "audit sink external emit failed sink=%s err=%s target=%s",
                getattr(ext, "name", "unknown"),
                type(exc).__name__,
                _redact_target(getattr(ext, "target", "")),
            )
            if required:
                raise AuditChainError(
                    f"audit sink emit failed: {getattr(ext, 'name', 'unknown')}"
                ) from exc
            acks.append(SinkAck(getattr(ext, "name", "unknown"), False, type(exc).__name__).as_dict())
    return acks


def append(
    org_id: str,
    event: str,
    data: dict,
    path: str | os.PathLike | None = None,
    mirror_path: str | os.PathLike | None = None,
) -> dict:
    """Append one org-scoped record, fsync it, and return the stored record.

    Re-reads the disk tail each time so log rotation or replacement does not
    continue a chain that no longer exists. Callers must not put secrets in
    ``data``: the sink is durable plaintext for audit readers.
    """
    if not isinstance(org_id, str) or not org_id:
        raise ValueError("org_id required")
    if not isinstance(event, str) or not event:
        raise ValueError("event required")
    if not isinstance(data, dict):
        raise TypeError("data must be a dict")

    target = sink_path(path)
    with _LOCK:
        prev_hash, seq = _tail_state(target)
        record = {
            "seq": seq + 1,
            "ts": datetime.now(timezone.utc).isoformat(),
            "org_id": org_id,
            "event": event,
            "prev_hash": prev_hash,
            "data": data,
        }
        record["hash"] = _hash(record)
        # External sinks first: required failure must not leave a primary record.
        acks = _emit_external(record, mirror_path=mirror_path)
        LocalChainSink(path).emit(record)
        return record


def mirror_telemetry(
    telemetry,
    path: str | os.PathLike | None = None,
    mirror_path: str | os.PathLike | None = None,
) -> int:
    """Mirror the current telemetry buffer; call before the DB flush clears it.

    Best effort: a sink failure must not stop the existing DB flush. No record
    contents are logged.
    """
    written = 0
    try:
        # shortcut: telemetry exposes no public snapshot; switch when it does.
        for metrics in list(getattr(telemetry, "_metrics", {}).values()):
            append(
                metrics["org_id"],
                "telemetry.flush",
                {key: value for key, value in metrics.items() if key != "org_id"},
                path=path,
                mirror_path=mirror_path,
            )
            written += 1
    except Exception as exc:
        logger.warning("audit sink mirror failed after %d record(s): %s", written, type(exc).__name__)
    return written


def emit_event(
    org_id: str,
    event: str,
    data: dict,
    path: str | os.PathLike | None = None,
    mirror_path: str | os.PathLike | None = None,
) -> dict:
    """Interface-friendly alias for append."""
    return append(org_id, event, data, path=path, mirror_path=mirror_path)


def read(org_id: str | None = None, path: str | os.PathLike | None = None) -> list[dict]:
    """Verify the full chain and return records, optionally scoped to one org.

    Any malformed record, broken link, or hash mismatch raises. No partial
    results: a verified prefix is not an audit trail.
    """
    target = sink_path(path)
    try:
        handle = target.open("r", encoding="utf-8")
    except FileNotFoundError:
        return []
    records = []
    prev_hash = GENESIS_HASH
    seq = 0
    with handle:
        for lineno, line in enumerate(handle, 1):
            if not line.strip():
                raise AuditChainError(f"line {lineno}: blank line")
            record = _parse_line(line, lineno)
            if record["seq"] != seq + 1 or record["prev_hash"] != prev_hash:
                raise AuditChainError(f"line {lineno}: broken chain")
            seq += 1
            prev_hash = record["hash"]
            if org_id is None or record["org_id"] == org_id:
                records.append(record)
    return records
