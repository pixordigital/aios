"""Unit & integration tests for Simple Mode (Camada Não-Técnica)."""

from aios.core.simple_compiler import (
    PLUG_AND_PLAY_SOLUTIONS,
    compile_plug_and_play_agent,
)


def test_compile_default_whatsapp_atendente():
    compiled = compile_plug_and_play_agent(
        solution_key="whatsapp_atendente",
        name="Bia da Loja",
        business_name="Pizzaria da Nonna",
        business_description="Pizzas artesanais e vinhos, entrega em até 40 min",
        intelligence_level="fast",
        tone="amigavel",
        rules=["no_invent_price", "human_handover"],
        faq_text="Entregamos de terça a domingo das 18h às 23h.",
        business_hours="Segunda a Domingo das 18h às 23h",
        off_hours_behavior="take_note",
    )

    assert compiled["name"] == "Bia da Loja"
    assert compiled["agent_type"] == "support"
    assert compiled["llm_config"]["model"] == "openai/gpt-4o-mini"
    assert compiled["llm_config"]["temperature"] == 0.5
    assert "Pizzaria da Nonna" in compiled["system_prompt"]
    assert "Pizzas artesanais" in compiled["system_prompt"]
    assert "NUNCA invente preços" in compiled["system_prompt"]
    assert "transferindo para a equipe humana" in compiled["system_prompt"]
    assert "Entregamos de terça a domingo" in compiled["system_prompt"]
    assert "Fora do horário comercial" in compiled["system_prompt"]
    assert "transcribe" in compiled["tools"]
    assert compiled["governance_config"]["autonomy"] == "autonomous"
    assert compiled["extra_data"]["simple_config"]["created_via"] == "simple_mode"


def test_compile_sdr_vendedor_deep_model():
    compiled = compile_plug_and_play_agent(
        solution_key="sdr_vendedor",
        name="",
        business_name="Consultoria Tech",
        business_description="Desenvolvimento de software sob medida",
        intelligence_level="deep",
        tone="profissional",
        rules=["confirm_data"],
        business_hours="Seg a Sex 09h às 18h",
    )

    assert "Consultoria Tech" in compiled["name"]
    assert compiled["agent_type"] == "sdr"
    assert compiled["llm_config"]["model"] == "openai/gpt-4o"
    assert compiled["llm_config"]["temperature"] == 0.4
    assert "Profissional, elegante" in compiled["system_prompt"]
    assert "crm_create_deal" in compiled["tools"]


def test_all_solutions_compile_cleanly():
    for key in PLUG_AND_PLAY_SOLUTIONS:
        res = compile_plug_and_play_agent(solution_key=key)
        assert res["name"]
        assert res["agent_type"]
        assert len(res["system_prompt"]) > 50
        assert res["llm_config"]["model"]
        assert res["extra_data"]["simple_config"]["solution_key"] == key


def test_view_mode_toggle_routes():
    from starlette.testclient import TestClient
    from aios.main import app

    c = TestClient(app, follow_redirects=False)

    # 1. /dashboard/view-mode/simple sets cookie
    r = c.get("/dashboard/view-mode/simple")
    assert r.status_code == 303
    assert r.cookies.get("aios_view_mode") == "simple"

    # 2. /dashboard/view-mode/pro sets cookie
    r = c.get("/dashboard/view-mode/pro")
    assert r.status_code == 303
    assert r.cookies.get("aios_view_mode") == "pro"

    # 3. /dashboard/toggle-mode flips simple to pro
    r = c.get("/dashboard/toggle-mode", cookies={"aios_view_mode": "simple"})
    assert r.status_code == 303
    assert r.cookies.get("aios_view_mode") == "pro"

    # 4. /dashboard/toggle-mode flips pro to simple
    r = c.get("/dashboard/toggle-mode", cookies={"aios_view_mode": "pro"})
    assert r.status_code == 303
    assert r.cookies.get("aios_view_mode") == "simple"


def test_templates_load_cleanly():
    """Validates that Jinja compiles all new simple mode templates without syntax errors."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("aios/dashboard/templates"))
    
    # Check that our new templates exist and parse without syntax errors
    for tpl_name in [
        "simple_home.html",
        "simple_assistant_wizard.html",
        "simple_assistants.html",
        "simple_inbox.html",
        "simple_knowledge.html",
    ]:
        tpl = env.get_template(tpl_name)
        assert tpl is not None


def test_every_solution_tool_exists_in_registry():
    """A compiled agent must only reference tools the runtime can resolve."""
    from aios.tools.registry import TOOL_REGISTRY

    for key in PLUG_AND_PLAY_SOLUTIONS:
        res = compile_plug_and_play_agent(solution_key=key)
        missing = [t for t in res["tools"] if t not in TOOL_REGISTRY]
        assert not missing, f"{key}: unknown tools {missing}"


def test_removed_surfaces_have_no_route():
    """The pilot-gated surfaces must not exist: no handler may claim them."""
    from aios.dashboard.app import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/dashboard/simple/alerts" not in paths
    assert "/dashboard/simple/knowledge/quick-teach" not in paths
    assert "/dashboard/simple/knowledge/upload" in paths
    assert "/dashboard/simple/knowledge/{art_id}/delete" in paths
