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

MANAGERS = ["manager_sales", "manager_dev", "manager_red", "manager_blue"]


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
