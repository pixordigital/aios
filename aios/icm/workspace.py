"""Safe workspace path and bounded layered-context helpers for ICM-X."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DEFAULT_MAX_FILE_BYTES = 128 * 1024
DEFAULT_MAX_CONTEXT_CHARS = 48 * 1024


def _validate_segment(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SEGMENT.fullmatch(value):
        raise ValueError(f"invalid {label}")
    if value in {".", ".."}:
        raise ValueError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class WorkspacePaths:
    """Tenant-scoped workspace layout rooted under a configured data directory."""
    storage_root: Path

    def _root(self) -> Path:
        return self.storage_root.expanduser().resolve()

    def workspace(self, org_id: str, workspace_id: str) -> Path:
        org = _validate_segment(org_id, "organization id")
        workspace = _validate_segment(workspace_id, "workspace id")
        return self._root() / "tenants" / org / "workspaces" / workspace

    def run(self, org_id: str, workspace_id: str, run_id: str) -> Path:
        run = _validate_segment(run_id, "run id")
        return self.workspace(org_id, workspace_id) / "runs" / run

    def artifact(self, org_id: str, workspace_id: str, run_id: str, name: str) -> Path:
        filename = _validate_segment(name, "artifact name")
        return self.run(org_id, workspace_id, run_id) / "artifacts" / filename

    def ensure_run_directories(self, org_id: str, workspace_id: str, run_id: str) -> Path:
        """Create an isolated run directory and reject symlink escapes."""
        root = self._root()
        root.mkdir(parents=True, exist_ok=True)
        components = ("tenants", org_id, "workspaces", workspace_id, "runs", run_id)
        current = root
        for component in components:
            current = current / component
            resolved = current.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("workspace path escapes configured storage root")
            current.mkdir(exist_ok=True)
            current = current.resolve()
            if not current.is_relative_to(root):
                raise ValueError("workspace path escapes configured storage root")

        for directory in ("artifacts", "provenance"):
            child = current / directory
            resolved = child.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("workspace path escapes configured storage root")
            child.mkdir(exist_ok=True)
        return current


def load_context_files(
    workspace_root: str | Path,
    files_by_layer: Mapping[str, list[str]],
    *,
    allowed_layers: list[str] | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> tuple[str, dict[str, str]]:
    """Read selected context files with traversal and size protection.

    Returns assembled text and relative-path SHA-256 fingerprints. Dynamic
    business data should normally be fetched through authorized tools.
    """
    root = Path(workspace_root).expanduser().resolve()
    selected_layers = set(files_by_layer if allowed_layers is None else allowed_layers)
    sections: list[str] = []
    fingerprints: dict[str, str] = {}
    total_chars = 0

    for layer, paths in files_by_layer.items():
        if layer not in selected_layers:
            continue
        if not isinstance(paths, list):
            raise ValueError(f"context layer {layer!r} must contain a list of paths")
        for relative in paths:
            candidate = (root / relative).resolve()
            if not candidate.is_relative_to(root):
                raise ValueError(f"context path escapes workspace: {relative}")
            if not candidate.is_file():
                continue
            content_bytes = candidate.read_bytes()
            if len(content_bytes) > max_file_bytes:
                raise ValueError(f"context file exceeds size limit: {relative}")
            content = content_bytes.decode("utf-8")
            if total_chars + len(content) > max_total_chars:
                raise ValueError("assembled context exceeds configured character budget")
            total_chars += len(content)
            rel = candidate.relative_to(root).as_posix()
            fingerprints[rel] = hashlib.sha256(content_bytes).hexdigest()
            sections.append(f"## {layer}: {rel}\n\n{content.strip()}")

    return "\n\n".join(sections), fingerprints
