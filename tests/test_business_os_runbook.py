"""Smoke tests for Business OS runbook scaffold."""
from pathlib import Path


RUNBOOK = Path(__file__).resolve().parents[1] / "docs" / "business-os-runbook.md"


def test_business_os_runbook_exists():
    assert RUNBOOK.is_file(), f"missing: {RUNBOOK}"


def test_business_os_runbook_has_required_sections():
    text = RUNBOOK.read_text(encoding="utf-8")
    for section in [
        "Onboarding",
        "Permissões",
        "Backup",
        "Deploy",
        "Incidente",
        "Humano responsável",
    ]:
        assert section in text, f"missing section: {section}"
