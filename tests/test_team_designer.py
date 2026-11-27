"""Phase 4: team designer — clone/adapt base solution into a new named pack."""

from aios.core.agent_pack import validate_agent_pack
from aios.core.solution_pack import design_team_pack


def test_design_team_pack_clones_base_and_validates():
    m = design_team_pack("vender", "clinica de estetica", "Voce e o time comercial da clinica.")
    validated = validate_agent_pack(m)
    assert validated.version == "1.0.0"
    assert validated.identity.id == "sol-vender-clinica-de-estetica"
    assert "clinica de estetica" in validated.identity.description
    assert validated.identity.tags == ["vender", "clinica-de-estetica"]
    assert validated.runtime_targets[0].target == "docker"
