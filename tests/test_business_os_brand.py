"""BusinessOS Brand Kit template sanity checks."""
from pathlib import Path

BRAND_KIT = (
    Path(__file__).resolve().parents[1]
    / "aios"
    / "templates"
    / "business_os"
    / "Brand-Kit.md"
)

# Real/common brands — none of these may appear in the kit, especially in the
# first five lines, which introduce the file.
FORBIDDEN_BRANDS = (
    "Nike", "Apple", "Google", "Amazon", "Coca-Cola", "Pepsi", "Tesla",
    "McDonalds", "Red Bull", "Samsung", "Microsoft", "Meta", "BMW",
)


def test_brand_kit_file_exists():
    assert BRAND_KIT.exists()


def test_brand_kit_is_one_person_os():
    text = BRAND_KIT.read_text()
    assert "one-person" in text


def test_brand_kit_no_brand_names_in_first_five_lines():
    first5 = BRAND_KIT.read_text().splitlines()[:5]
    for name in FORBIDDEN_BRANDS:
        assert name not in "".join(first5)
