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

    def stage(self, org_id: str, workspace_id: str, stage_id: str) -> Path:
        stage = _validate_segment(stage_id, "stage id")
        return self.workspace(org_id, workspace_id) / "L2" / "stages" / stage

    def ensure_workspace_scaffold(self, org_id: str, workspace_id: str) -> Path:
        """Create standard ICM-X workspace layer directories."""
        ws = self.workspace(org_id, workspace_id)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "L0").mkdir(exist_ok=True)
        (ws / "L1").mkdir(exist_ok=True)
        (ws / "L2" / "stages").mkdir(parents=True, exist_ok=True)
        (ws / "L3" / "static").mkdir(parents=True, exist_ok=True)
        return ws

    def ensure_run_directories(self, org_id: str, workspace_id: str, run_id: str) -> Path:
        """Create an isolated run directory and reject symlink escapes."""
        root = self._root()
        root.mkdir(parents=True, exist_ok=True)
        org = _validate_segment(org_id, "organization id")
        workspace = _validate_segment(workspace_id, "workspace id")
        run = _validate_segment(run_id, "run id")
        components = ("tenants", org, "workspaces", workspace, "runs", run)
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


def seed_b2b_lead_research_workspace(
    storage_root: str | Path,
    org_id: str = "default",
    workspace_id: str = "b2b_lead_research",
) -> Path:
    """Create and populate a standard versioned B2B lead-research workspace."""
    paths = WorkspacePaths(Path(storage_root))
    ws_dir = paths.ensure_workspace_scaffold(org_id, workspace_id)

    # L0: Workspace identity
    (ws_dir / "L0" / "WORKSPACE.md").write_text(
        """# B2B Lead Research & Qualification Workspace

- ID: `b2b_lead_research`
- Version: `1.0.0`
- Purpose: Discover, research, normalize, and qualify prospective B2B organizations matching specified Ideal Customer Profile (ICP) criteria.
- Authority: Context references only; live CRM records and outreach are governed by authoritative AIOS tools.
""",
        encoding="utf-8",
    )

    # L1: Routing policies
    (ws_dir / "L1" / "ROUTES.md").write_text(
        """# Routing Policies

- `company_research` -> discover candidate companies using public directories and web search; normalize identity and public contact points.
- `lead_qualification` -> evaluate scoring criteria and rubric weights; produce qualified leads for SDR review.
- Prohibited: direct external messaging or WhatsApp outreach from research stages.
""",
        encoding="utf-8",
    )

    # L2: company_research stage
    cr_stage = paths.stage(org_id, workspace_id, "company_research")
    cr_stage.mkdir(parents=True, exist_ok=True)
    (cr_stage / "stage.yaml").write_text(
        """id: company_research
version: 1.0.0
description: Research and normalize prospect companies matching ICP criteria
mode: llm
timeout_seconds: 60
max_llm_calls: 2
max_cost_usd: 0.05
inputs_schema: lead_research_input.v1
outputs_schema: company_research_output.v1
context:
  layers: [identity, routing, stage, static_references]
  max_context_tokens: 6000
allowed_tools: [company_lookup, web_search, http_get]
denied_tools: [crm_update, whatsapp_send]
side_effects: false
approval_required: false
retry:
  max_attempts: 2
  retry_on: [timeout, transient_provider_error, invalid_output]
  no_retry_on: [permission_denied, invalid_input]
""",
        encoding="utf-8",
    )
    (cr_stage / "CONTEXT.md").write_text(
        """# Stage Instructions: Company Research

1. Consume target ICP specifications (industry, employee range, region, buying signals).
2. Query public search tools to identify candidate organizations.
3. Validate company website existence and business alignment via public pages.
4. Extract structured metadata: legal/trading name, domain, headquarters, employee estimate, primary activity.
5. Do NOT collect personal sensitive data. Rely only on public corporate data (LGPD compliant).
""",
        encoding="utf-8",
    )

    # L2: lead_qualification stage
    lq_stage = paths.stage(org_id, workspace_id, "lead_qualification")
    lq_stage.mkdir(parents=True, exist_ok=True)
    (lq_stage / "stage.yaml").write_text(
        """id: lead_qualification
version: 1.0.0
description: Score and qualify discovered leads against ICP criteria
mode: hybrid
timeout_seconds: 45
max_llm_calls: 1
max_cost_usd: 0.02
inputs_schema: company_research_output.v1
outputs_schema: lead_qualification_output.v1
context:
  layers: [identity, stage, static_references]
  max_context_tokens: 4000
allowed_tools: [lead_score, calculator]
denied_tools: [whatsapp_send]
side_effects: false
approval_required: false
retry:
  max_attempts: 2
  retry_on: [timeout, transient_provider_error]
  no_retry_on: [permission_denied, invalid_input]
""",
        encoding="utf-8",
    )
    (lq_stage / "CONTEXT.md").write_text(
        """# Stage Instructions: Lead Qualification

1. Score candidate companies against the ICP rubric (0 to 100):
   - Sector alignment: up to 30 points.
   - Headcount/scale match: up to 20 points.
   - Regional match: up to 15 points.
   - Verified buying signals: up to 25 points.
   - Public corporate contact available: up to 10 points.
2. Flag leads scoring >= 70 as qualified for SDR handoff.
3. Generate structured qualification reasoning and citation links.
""",
        encoding="utf-8",
    )

    # L3: Static reference guidelines
    (ws_dir / "L3" / "static" / "icp_guidelines.md").write_text(
        """# B2B Ideal Customer Profile Guidelines

- Target segment: Mid-market and enterprise B2B service providers and SaaS companies.
- Privacy & Compliance: Strictly adhere to LGPD / GDPR. Only public corporate information is processed.
- Data Quality: Every data point must have a verifiable source URL.
""",
        encoding="utf-8",
    )

    return ws_dir
