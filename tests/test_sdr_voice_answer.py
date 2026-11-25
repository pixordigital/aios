"""SDR Voice Answer: profile YAML parse + profile_doc_from_extra_data no-dupes."""
from pathlib import Path

import pytest
import yaml

from aios.core import business_sdr, sdr_prompt

_YAML_PATH = (
    Path(__file__).parent.parent
    / "aios"
    / "templates"
    / "business_os"
    / "SDR"
    / "profile-SDR-doctypes.yaml"
)


def test_profile_yaml_parses():
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    assert data["fields"]
    assert data["fields"][0]["name"]
    assert data["whatsapp"]["channel_type"] == "whatsapp"


def test_profile_doc_from_extra_data_no_duplicates():
    bad = {"fields": [{"name": "lead_phone"}, {"name": "lead_phone"}]}
    with pytest.raises(ValueError, match="duplicate"):
        business_sdr.profile_doc_from_extra_data({"waba_templates": bad})


def test_profile_doc_from_extra_data_adapts_waba_templates():
    waba = {"fields": [{"name": "a", "kind": "string", "domain": "email", "required": True}]}
    doc = business_sdr.profile_doc_from_extra_data({"waba_templates": waba})
    assert doc["doc_type"] == "whatsapp"
    assert doc["fields"] == waba["fields"]


def test_profile_doc_from_extra_data_rejects_bad_doc_type():
    with pytest.raises(ValueError, match="unsupported doc_type"):
        business_sdr.profile_doc_from_extra_data({}, doc_type="voice")


def test_profile_doc_from_extra_data_bot_doc_type():
    doc = business_sdr.profile_doc_from_extra_data({}, doc_type="whatsapp_bot")
    assert doc["doc_type"] == "whatsapp_bot"


def test_sdr_prompt_shape():
    out = sdr_prompt.sdr_prompt({"duplicated_numbers": ["11999887766", "11999887766"]})
    assert out["vora"] == "default"
    assert out["dials"] == 1 and out["visits"] == 0
    assert out["risks"]
