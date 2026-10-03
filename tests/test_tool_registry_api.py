"""The flow builder palette, node modal, and save validation all read the
code registry — so what it returns is pinned here, not assumed in JS.

The failure this prevents: the palette/modal offered `evolution` and
`whatsapp`, which were never in TOOL_REGISTRY, so every node built from
them failed at run time with "Unknown tool".
"""

from aios.api.tools import registry_entries


def test_registry_lists_every_runnable_tool():
    from aios.tools.registry import TOOL_REGISTRY

    entries = registry_entries()
    assert {e["name"] for e in entries} == set(TOOL_REGISTRY)


def test_ghost_tools_are_absent():
    names = {e["name"] for e in registry_entries()}
    assert "evolution" not in names
    assert "whatsapp" not in names


def test_entries_carry_descriptions_and_schemas():
    for e in registry_entries():
        assert e["description"], e["name"]
        assert isinstance(e["input_schema"], dict)


def test_known_tool_schema_has_real_properties():
    by_name = {e["name"]: e for e in registry_entries()}
    props = by_name["sql_query"]["input_schema"].get("properties", {})
    assert "query" in props
