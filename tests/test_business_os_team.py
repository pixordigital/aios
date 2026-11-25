"""BusinessOS Team expansion templates - generic, no brand mimicry."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
TEAM = ROOT / "aios/templates/business_os/Team"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TEAM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_team_files_exist():
    assert (TEAM / "README.md").exists()
    assert (TEAM / "expansion_analyst.py").exists()
    assert (TEAM / "retention_watch.py").exists()


def test_expansion_template_shape():
    mod = _load("expansion_analyst")
    t = mod.EXPANSION_TEMPLATE
    assert t["agent_type"] == "custom"
    assert "system_prompt" in t and len(t["system_prompt"]) > 50
    assert "tools" in t and "lead_score" in t["tools"]


def test_retention_template_shape():
    mod = _load("retention_watch")
    t = mod.RETENTION_WATCH_TEMPLATE
    assert t["agent_type"] == "custom"
    assert "system_prompt" in t and len(t["system_prompt"]) > 50
    assert "tools" in t and "sql_query" in t["tools"]
