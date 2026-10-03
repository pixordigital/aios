"""Shared stateless tools must not be reported as team conflicts.

Every normal team shares sql_query/web_search/http_request across its agents.
Flagging those as "contenção" was noise, and at /dashboard/teams/{id} it also
blocked saving the team with a 422.
"""

from aios.dashboard.app import _tool_conflicts


def test_shared_stateless_tools_are_not_conflicts():
    team = [
        ["sql_query", "web_search", "http_request", "read_file", "calculator"],
        ["sql_query", "web_search", "python_sandbox", "current_datetime"],
    ]
    assert _tool_conflicts(team) == []


def test_stateful_tool_shared_by_two_agents_is_flagged():
    team = [["crm_create_deal", "sql_query"], ["crm_create_deal", "sql_query"]]
    conflicts = _tool_conflicts(team)
    assert len(conflicts) == 1
    assert "crm_create_deal" in conflicts[0]


def test_single_agent_never_conflicts():
    assert _tool_conflicts([["crm_create_deal", "sql_query", "crm_create_deal"]]) == []
