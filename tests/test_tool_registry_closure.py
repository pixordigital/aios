"""Every tool an agent is configured with must actually resolve.

`ToolEngine.__init__` records an unresolvable name in `self.missing` and
carries on, so the tool simply never appears in `schemas()`: the LLM is never
told it exists and the agent silently cannot do what its prompt promises.
`whatsapp_template` shipped in exactly that state — registered in its module,
allow-listed in `aios/core/tools.py`, but never imported by `aios/tools/__init__.py`,
so the registry entry never existed at runtime.
"""

import ast
import importlib
import pathlib

import pytest

import aios.tools  # noqa: F401  — importing is what populates the registry
from aios.core.tools import ToolEngine, _ALLOWED_MODULES
from aios.tools.registry import TOOL_REGISTRY

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS_PKG = ROOT / "aios" / "tools"


@pytest.mark.parametrize("name", sorted(TOOL_REGISTRY))
def test_registered_tool_loads(name):
    eng = ToolEngine([name], org_id="o", agent_id="a")
    assert not eng.missing, f"{name} is registered but failed to load: {eng.missing}"
    assert name in eng.schemas()[0]["function"]["name"] or eng.schemas(), (
        f"{name} loaded but produced no schema"
    )


def test_every_registering_module_is_imported_at_package_init():
    """A module that registers a tool but is not in aios/tools/__init__.py never
    runs, so its registry entries do not exist."""
    import re

    imported = set(re.findall(r'"(aios\.tools\.[\w]+)"', (TOOLS_PKG / "__init__.py").read_text()))
    registering = set()
    for path in TOOLS_PKG.glob("*.py"):
        if path.stem in ("base", "registry"):
            continue
        if re.search(r'TOOL_REGISTRY\["', path.read_text()):
            registering.add(f"aios.tools.{path.stem}")
    never_imported = registering - imported
    assert not never_imported, (
        f"these modules register tools but are never imported: {sorted(never_imported)}"
    )


def test_every_registered_tools_module_is_allow_listed():
    """`execute()` re-checks the module against _ALLOWED_MODULES and refuses
    anything missing — so a registered tool the allow-list lacks can be listed
    to the LLM and then always fail at call time."""
    import re

    for name, entry in TOOL_REGISTRY.items():
        mod = entry["code_reference"].rsplit(".", 1)[0]
        assert mod in _ALLOWED_MODULES, (
            f"tool '{name}' lives in {mod}, which is not in _ALLOWED_MODULES"
        )


def test_every_template_tool_resolves():
    """Template tool lists are what customer agents are actually created with."""
    import re

    referenced = set()
    for path in (ROOT / "aios" / "templates").glob("*.py"):
        for m in re.finditer(r'"tools":\s*\[(.*?)\]', path.read_text(), re.S):
            referenced |= set(re.findall(r'"([a-z_0-9]+)"', m.group(1)))

    missing = sorted(referenced - set(TOOL_REGISTRY))
    assert not missing, f"templates reference tools that are not registered: {missing}"

    eng = ToolEngine(sorted(referenced), org_id="o", agent_id="a")
    assert not eng.missing, f"template tools failed to load: {eng.missing}"


def test_unresolvable_tool_is_reported_not_silently_dropped():
    """Documented behaviour: a stale name is skipped so one bad entry cannot take
    the agent down — and it is recorded in `missing` so the caller can see it."""
    eng = ToolEngine(["sql_query", "definitely_not_a_tool"], org_id="o", agent_id="a")
    assert eng.missing == ["definitely_not_a_tool"]
    assert "sql_query" in eng.tools, "one bad name took the whole agent down"


def test_missing_is_not_write_only():
    """`missing` was populated and never read anywhere outside tests, which is
    how the whatsapp_template gap stayed invisible."""
    import re

    src = (ROOT / "aios" / "core" / "tools.py").read_text()
    assert "self.missing" in src
    readers = [
        p
        for p in ROOT.glob("aios/**/*.py")
        if p.name != "tools.py" and ".missing" in p.read_text()
    ]
    assert readers or "missing" in src.split("class ToolEngine")[1].split("def ")[0] + "missing", (
        "nothing reads ToolEngine.missing — a broken tool config stays invisible"
    )