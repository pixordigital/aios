"""ICM-X foundations for AIOS.

ICM-X keeps workspace/context conventions separate from the durable workflow
execution engine already provided by AIOS.
"""
from aios.icm.adapter import ICMStageAdapter
from aios.icm.contracts import StageManifest, load_stage_manifest, manifest_fingerprint
from aios.icm.schemas import SchemaValidationError, register_schema, unregister_schema, validate_schema
from aios.icm.workspace import (
    WorkspacePaths,
    load_context_files,
    seed_b2b_lead_research_workspace,
)

__all__ = [
    "ICMStageAdapter",
    "SchemaValidationError",
    "StageManifest",
    "WorkspacePaths",
    "load_context_files",
    "load_stage_manifest",
    "manifest_fingerprint",
    "register_schema",
    "seed_b2b_lead_research_workspace",
    "unregister_schema",
    "validate_schema",
]
