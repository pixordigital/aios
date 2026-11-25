"""Smoke tests for Business OS scope/limits honest-status doc."""
from pathlib import Path


DOC = Path(__file__).resolve().parents[1] / "docs" / "business-os-scope-limits.md"


def test_business_os_scope_limits_doc_exists():
    assert DOC.is_file(), f"missing: {DOC}"


def test_business_os_scope_limits_required_phrases():
    text = DOC.read_text(encoding="utf-8").lower()
    required = [
        "not live business automation",
        "not_configured",
        "human owner",
        "hitl",
    ]
    for phrase in required:
        assert phrase in text, f"missing required phrase: {phrase}"

    legal_phrase = (
        "no legal/tax/financial advice" in text
        or "não é aconselhamento jurídico" in text
        or "no legal, tax, or financial advice" in text
    )
    assert legal_phrase, "missing legal/tax/financial advice boundary"


def test_business_os_scope_limits_lists_unwired_domains():
    text = DOC.read_text(encoding="utf-8").lower()
    for domain in [
        "payment",
        "crm",
        "email",
        "whatsapp",
        "calendar",
        "fulfillment",
    ]:
        assert domain in text, f"missing domain: {domain}"
