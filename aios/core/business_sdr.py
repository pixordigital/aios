"""BusinessOS SDR "Voice Answer Systems" — profile doc from extra_data.

Canonical ProfileField doc: aios/templates/business_os/SDR/profile-SDR-doctypes.yaml.
Durable JSON in extra_data["waba_templates"] (since 2026-03-25) is adapted and
returned as-is; otherwise the canonical YAML doc is returned.
"""
import copy
from pathlib import Path

import yaml

_TEMPLATE_YAML = (
    Path(__file__).parent.parent
    / "templates"
    / "business_os"
    / "SDR"
    / "profile-SDR-doctypes.yaml"
)
SUPPORTED_DOC_TYPES = ("whatsapp", "whatsapp_bot")


def _assert_no_duplicate_keys(doc, where):
    names = [f.get("name") for f in (doc.get("fields") or []) if f.get("name")]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"duplicate profile keys in {where}: {dupes}")


def _default_profile_doc(doc_type):
    data = yaml.safe_load(_TEMPLATE_YAML.read_text(encoding="utf-8")) or {}
    doc = copy.deepcopy(data)
    doc["doc_type"] = doc_type
    doc.setdefault("fields", [])
    doc.setdefault("whatsapp", {})
    return doc


def profile_doc_from_extra_data(extra_data, doc_type="whatsapp"):
    """Profile doc for doc_type ("whatsapp" | "whatsapp_bot").

    Adapts durable extra_data["waba_templates"] JSON if present; returns it.
    """
    if doc_type not in SUPPORTED_DOC_TYPES:
        raise ValueError(f"unsupported doc_type: {doc_type}")
    waba = (extra_data or {}).get("waba_templates")
    if waba is None:
        return _default_profile_doc(doc_type)
    if not isinstance(waba, dict):
        raise ValueError("extra_data['waba_templates'] must be a dict")
    doc = copy.deepcopy(waba)
    doc["doc_type"] = doc_type
    _assert_no_duplicate_keys(doc, "waba_templates")
    return doc
