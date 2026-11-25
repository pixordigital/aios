"""Business OS legal/commercial boundaries checklist - human accountability, no legal advice."""
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "business-os-legal-boundaries.md"

# Real brands must not appear as endorsements/examples in a legal-boundary doc.
FORBIDDEN_BRANDS = (
    "Nike",
    "Apple",
    "Google",
    "Amazon",
    "Coca-Cola",
    "Pepsi",
    "Tesla",
    "McDonalds",
    "Red Bull",
    "Samsung",
    "Microsoft",
    "Meta",
    "BMW",
)


def test_legal_boundaries_doc_exists():
    assert DOC.exists(), f"Missing {DOC}"


def test_legal_boundaries_required_phrases():
    text = DOC.read_text(encoding="utf-8")
    required = [
        "não é aconselhamento jurídico",
        "humano responsável",
        "LGPD/privacidade",
        "contratos",
        "impostos/pagamentos",
        "HITL",
    ]
    for phrase in required:
        assert phrase in text, f"Missing required phrase: {phrase}"


def test_legal_boundaries_no_real_brand_endorsements():
    text = DOC.read_text(encoding="utf-8")
    for brand in FORBIDDEN_BRANDS:
        assert brand not in text, f"Real brand name must not appear: {brand}"
