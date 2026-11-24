"""Append-only, hash-chained JSONL sink for security telemetry.

Independent of the application DB by construction: the chain lives in a local
file and is verified from the file itself. A host-level compromise can still
rewrite the file (and recompute hashes), so this is tamper-evident, not
tamper-proof against root or the running service account.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
_TAIL_BYTES = 1 << 20
_LOCK = threading.Lock()
_FIELDS = {"seq", "ts", "org_id", "event", "prev_hash", "data", "hash"}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class AuditChainError(ValueError):
    """Raised when a record or the chain fails validation; fail closed."""


def sink_path(path: str | os.PathLike | None = None) -> Path:
    """Resolve the sink file: explicit arg, then env, then app data dir."""
    if path is not None:
        return Path(path).expanduser()
    configured = os.getenv("AIOS_AUDIT_SINK_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    from aios.config import settings

    base = Path(getattr(settings, "app_data_dir", "./data")).expanduser()
    return base / "audit" / "telemetry.jsonl"


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


def append(org_id: str, event: str, data: dict, path: str | os.PathLike | None = None) -> dict:
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
        payload = _canonical(record) + b"\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            if os.write(fd, payload) != len(payload):
                raise OSError("short audit write")
            os.fsync(fd)
        finally:
            os.close(fd)
        return record


def mirror_telemetry(telemetry, path: str | os.PathLike | None = None) -> int:
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
            )
            written += 1
    except Exception as exc:
        logger.warning("audit sink mirror failed after %d record(s): %s", written, type(exc).__name__)
    return written


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
