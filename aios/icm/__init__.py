"""ICM-X foundations for AIOS.

ICM-X keeps workspace/context conventions separate from the durable workflow
execution engine already provided by AIOS.
"""
from aios.icm.contracts import StageManifest, load_stage_manifest
from aios.icm.workspace import WorkspacePaths, load_context_files

__all__ = ["StageManifest", "WorkspacePaths", "load_context_files", "load_stage_manifest"]
