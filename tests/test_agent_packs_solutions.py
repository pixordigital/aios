"""Solution packs -> versioned AgentPackManifest (Phase 2 catalog)."""

from aios.core.agent_pack import pack_counts, validate_agent_pack
from aios.core.solution_pack import build_solution_pack, build_solution_pack_dict, solution_pack_keys


def test_solution_pack_keys_sorted():
    keys = solution_pack_keys()
    assert keys
    assert keys == sorted(keys)


def test_build_solution_pack_vender_valid():
    m = build_solution_pack("vender")
    validated = validate_agent_pack(m)
    assert validated.version == "1.0.0"
    assert validated.identity.id == "sol-vender"
    assert validated.identity.agent_type == "sdr"
    counts = pack_counts(validated.model_dump(mode="json"))
    assert counts["runtime_targets"] == 1


def test_build_solution_pack_all_solutions_validate():
    for key in solution_pack_keys():
        m = build_solution_pack(key)
        validate_agent_pack(m)
        build_solution_pack_dict(key)
