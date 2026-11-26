"""Smoke tests for Business OS sandbox/live-safe setup doc."""
from pathlib import Path


DOC = Path(__file__).resolve().parents[1] / "docs" / "business-os-sandbox-setup.md"


def test_business_os_sandbox_setup_doc_exists():
    assert DOC.is_file(), f"missing: {DOC}"


def test_business_os_sandbox_setup_doc_required_content():
    text = DOC.read_text(encoding="utf-8")
    for token in [
        "Cal.com",
        "RESEND_API_KEY",
        "EVOLUTION_SERVER_URL",
        "HITL",
        "shadow mode",
    ]:
        assert token in text, f"missing required token: {token}"
