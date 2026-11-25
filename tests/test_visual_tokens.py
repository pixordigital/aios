"""Visual tokens: generic file exists + parses + primary set."""
import os

import yaml


def test_visual_tokens_yaml_exists_and_parses():
    base = "aios/templates/business_os"
    path = os.path.join(base, "Visual", "tokens.yaml")
    assert os.path.isfile(path), f"missing {path}"
    data = yaml.safe_load(open(path, encoding="utf-8"))
    assert data["colors"]["primary"] == "#1e40af"
    assert data["typography"]["family"] != ""
