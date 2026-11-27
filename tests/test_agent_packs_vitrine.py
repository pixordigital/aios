"""Vitrine counts for Agent Packs (Phase 1)."""

from aios.core.agent_pack import pack_counts


def _manifest() -> dict:
    return {
        "schema_version": "1.0.0",
        "version": "1.0.0",
        "identity": {
            "id": "editorial-team",
            "name": "Editorial Team",
            "agent_type": "team",
            "description": "editorial squad",
            "owner": "team",
            "tags": ["editorial"],
        },
        "prompt": {"system_prompt": "You are the editorial coordinator.", "variables": [], "scaffold_required": True},
        "tools": {"allowed_tools": ["write_doc"], "denied_tools": ["delete_db"], "risk_classes": {"write_doc": "write"}},
        "routines": [
            {"id": "draft_chapter", "trigger": "chapter_ready", "workflow_id": "wf-draft", "stage_ref": "stages/draft.v1", "enabled": True},
            {"id": "review_chapter", "trigger": "draft_ready", "workflow_id": "wf-review", "stage_ref": "stages/review.v1", "enabled": True},
        ],
        "approvals": {
            "mode": "ask_tools",
            "required_for": ["publish"],
            "approval_ttl_seconds": 300,
            "explicit_preapproved_allowed": False,
        },
        "memory_scope": {
            "scopes": ["conversation", "agent", "team"],
            "max_short_term_messages": 100,
            "long_term_enabled": True,
            "episodic_enabled": True,
            "redact_patterns": [],
        },
        "runtime_targets": [
            {"target": "local_proc", "entrypoint": "main:run", "image": None, "resources": {}},
            {"target": "openbot", "entrypoint": "main:run", "image": None, "resources": {}},
        ],
        "changelog": [{"version": "1.0.0", "date": "2026-11-26", "summary": "init", "author": "pixor"}],
        "provenance": {
            "source": "git:test",
            "created_by": "tester",
            "created_at": "2026-11-26T00:00:00Z",
            "checksum_sha256": None,
            "signature": None,
            "parent_fingerprint": None,
        },
    }


def test_pack_counts_empty_manifest():
    counts = pack_counts(None)
    assert counts["routines"] == 0
    assert counts["approval_mode"] == "ask_tools"
    assert counts["approval_required"] == 0
    assert counts["runtime_targets"] == 0
    assert counts["memory_scopes"] == 0
    assert counts["memory_long_term"] is False


def test_pack_counts_from_manifest():
    counts = pack_counts(_manifest())
    assert counts["routines"] == 2
    assert counts["approval_mode"] == "ask_tools"
    assert counts["approval_required"] == 1
    assert counts["runtime_targets"] == 2
    assert counts["memory_scopes"] == 3
    assert counts["memory_long_term"] is True
