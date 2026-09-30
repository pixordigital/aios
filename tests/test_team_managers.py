"""Per-team manager prompts and tool sets.

Every manager reused the single sales H2H/MEDDIC template, so the dev manager
coached engineers about discount approval and the red/blue security managers
carried CRM tools. These pin each manager's tool set to what its own team
actually uses.
"""

import re

import pytest

from aios.core.tools import ToolEngine
from aios.templates import TEMPLATES, apply_template
from aios.tools.registry import TOOL_REGISTRY

MANAGERS = ["manager_sales", "manager_dev", "manager_red", "manager_blue",
            "manager_data"]


class TestManagerTemplates:
    @pytest.mark.parametrize("key", MANAGERS)
    def test_registered(self, key):
        assert key in TEMPLATES

    @pytest.mark.parametrize("key", MANAGERS)
    def test_every_tool_exists(self, key):
        missing = [t for t in apply_template(key)["tools"] if t not in TOOL_REGISTRY]
        assert not missing, f"{key} references tools that do not exist: {missing}"

    @pytest.mark.parametrize("key", MANAGERS)
    def test_every_tool_loads(self, key):
        eng = ToolEngine(apply_template(key)["tools"], org_id="o")
        assert eng.missing == [], eng.missing

    @pytest.mark.parametrize("key", MANAGERS)
    def test_prompt_is_team_specific_not_sales(self, key):
        p = apply_template(key)["system_prompt"]
        if key != "manager_sales":
            # MEDDIC / discount-approval language belongs to sales alone.
            assert "MEDDIC" not in p
            assert "desconto" not in p.lower()

    def test_no_phantom_approval_tool(self):
        """The old sales prompt said 'use the approval tool'. It never existed.

        Real approvals flow through crm_update_deal's internal HITL into
        PendingAction, then /dashboard/approvals. Checked against the prompts
        themselves — the module docstring names the tool while documenting the
        defect, so scanning the whole file would match itself.
        """
        for key in MANAGERS:
            p = apply_template(key)["system_prompt"]
            assert "`approval` tool" not in p
            assert "`pending_approval`" not in p

    def test_no_stray_cjk(self):
        from pathlib import Path

        src = Path("aios/templates/team_managers.py").read_text()
        assert not re.findall(r"[\u4e00-\u9fff]", src)

    def test_agent_type_stays_manager(self):
        """Voice routing and queries branch on agent_type == 'manager'."""
        for key in MANAGERS:
            assert apply_template(key)["agent_type"] == "manager"


class TestManagerToolsMatchTeam:
    """A manager must be able to inspect the work its own workers do."""

    def _tools(self, key):
        return set(apply_template(key)["tools"])

    def test_red_manager_is_read_only(self):
        """red-agent is read-only by design; the manager must not outrank it."""
        assert "code" not in self._tools("manager_red")

    def test_blue_manager_can_patch(self):
        """blue-agent's job is to write the fix; the manager reviews it."""
        assert "code" in self._tools("manager_blue")

    def test_non_sales_managers_have_no_crm_tools(self):
        for key in ("manager_dev", "manager_red", "manager_blue"):
            crm = {t for t in self._tools(key) if t.startswith("crm_")}
            assert not crm, f"{key} holds sales-domain tools: {crm}"

    def test_dev_manager_sees_worker_tools(self):
        workers = {"read_file", "code", "sql_query", "python_sandbox", "web_search"}
        assert workers <= self._tools("manager_dev")

    def test_red_manager_sees_worker_tools(self):
        workers = {"read_file", "web_search", "http_request", "python_sandbox"}
        assert workers <= self._tools("manager_red")

    def test_sales_manager_sees_crm_and_external_crm(self):
        t = self._tools("manager_sales")
        assert {"crm_list_deals", "crm_stale_deals", "crm_update_deal"} <= t
        # workers push to HubSpot/Pipedrive/RDStation; the manager needs to see them
        assert {"hubspot", "pipedrive", "rdstation"} <= t

    @pytest.mark.parametrize("key", MANAGERS)
    def test_manager_is_superset_of_its_workers(self, key):
        """A manager that cannot run its workers' tools cannot check their work.

        Checked against the live team definitions in the template set: every
        worker tool must be reachable from the manager.
        """
        workers = {
            "manager_sales": ["sdr", "closer"],
            "manager_dev": ["frontend", "backend"],
            "manager_red": ["red"],
            "manager_blue": ["blue"],
            "manager_data": ["data_analyst", "data_scientist"],
        }[key]
        needed = set()
        for w in workers:
            needed |= set(apply_template(w)["tools"])
        missing = needed - self._tools(key)
        assert not missing, f"{key} cannot inspect worker tools: {sorted(missing)}"


WORKER_TEAMS = {
    "manager_sales": ["sdr", "closer"],
    "manager_dev": ["frontend", "backend"],
    "manager_red": ["red"],
    "manager_blue": ["blue"],
    "manager_data": ["data_analyst", "data_scientist"],
}


class TestPerAgentTools:
    """Tool sets must match what each agent does, and differ between peers."""

    @pytest.mark.parametrize("key", [
        "sdr", "closer", "frontend", "backend", "red", "blue",
        "data_analyst", "data_scientist",
    ])
    def test_worker_tools_all_exist_and_load(self, key):
        tools = apply_template(key)["tools"]
        missing = [t for t in tools if t not in TOOL_REGISTRY]
        assert not missing, f"{key}: {missing}"
        assert ToolEngine(tools, org_id="o").missing == []

    @pytest.mark.parametrize("mgr,workers", list(WORKER_TEAMS.items()))
    def test_manager_is_superset_of_its_workers(self, mgr, workers):
        needed = set()
        for w in workers:
            needed |= set(apply_template(w)["tools"])
        missing = needed - set(apply_template(mgr)["tools"])
        assert not missing, f"{mgr} cannot inspect {sorted(missing)}"

    # --- differentiation between peers doing different jobs ---

    def test_sdr_and_closer_differ(self):
        """SDR researches and qualifies; closer prices and consolidates."""
        sdr, closer = set(apply_template("sdr")["tools"]), set(apply_template("closer")["tools"])
        assert sdr != closer, "SDR and closer had byte-identical tool sets"
        assert {"lead_score", "web_search"} <= sdr
        assert "calculator" not in sdr
        assert {"calculator", "crm_merge_deals"} <= closer
        assert "lead_score" not in closer

    def test_analyst_and_scientist_differ(self):
        """Analyst reads call/voice data; scientist works the model."""
        a, s = set(apply_template("data_analyst")["tools"]), set(apply_template("data_scientist")["tools"])
        assert "transcribe" in a
        assert "transcribe" not in s

    def test_frontend_never_touches_the_database(self):
        assert "sql_query" not in apply_template("frontend")["tools"]

    def test_backend_can_verify_its_own_routes(self):
        """dev-backend owns the FastAPI layer; without http_request it could
        not check a route fix. dev-frontend had it, which was backwards."""
        assert "http_request" in apply_template("backend")["tools"]

    def test_red_stays_read_only(self):
        assert "code" not in apply_template("red")["tools"]
        assert "code" not in apply_template("manager_red")["tools"]

    def test_blue_can_write_and_prove(self):
        t = apply_template("blue")["tools"]
        assert "code" in t
        assert "sql_query" in t  # must show the query now filters org

    def test_sales_agents_know_the_date(self):
        """Follow-up scheduling is date-relative; both needed current_datetime."""
        for k in ("sdr", "closer", "manager_sales"):
            assert "current_datetime" in apply_template(k)["tools"], k

    def test_data_agents_can_reach_the_knowledge_base(self):
        """rag_search was reachable from 1 of 21 templates."""
        for k in ("data_analyst", "data_scientist", "manager_data",
                  "sdr", "closer", "manager_sales"):
            assert "rag_search" in apply_template(k)["tools"], k

    def test_no_sales_tools_outside_sales(self):
        for k in ("frontend", "backend", "red", "blue",
                  "data_analyst", "data_scientist",
                  "manager_dev", "manager_red", "manager_blue", "manager_data"):
            crm = {t for t in apply_template(k)["tools"] if t.startswith("crm_")}
            assert not crm, f"{k} holds sales-domain tools: {crm}"

    def test_no_writing_tools_for_read_only_roles(self):
        """send_email reaches real people; only sales may send it."""
        for k in ("frontend", "backend", "red", "blue",
                  "data_analyst", "data_scientist",
                  "manager_dev", "manager_red", "manager_blue", "manager_data"):
            assert "send_email" not in apply_template(k)["tools"], k
