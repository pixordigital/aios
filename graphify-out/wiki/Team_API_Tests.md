# Team API Tests

> 19 nodes · cohesion 0.15

## Key Concepts

- **AsyncClient** (8 connections)
- **TestTeams** (6 connections) — `tests/test_teams.py`
- **TestTeamManagerRequired** (5 connections) — `tests/test_teams.py`
- **test_teams.py** (4 connections) — `tests/test_teams.py`
- **.test_manager_from_other_org_rejected()** (3 connections) — `tests/test_teams.py`
- **.test_team_with_manager_accepted()** (3 connections) — `tests/test_teams.py`
- **.test_team_without_manager_rejected()** (3 connections) — `tests/test_teams.py`
- **.test_assign_agents_to_team()** (3 connections) — `tests/test_teams.py`
- **.test_delete_team()** (3 connections) — `tests/test_teams.py`
- **.test_get_team()** (3 connections) — `tests/test_teams.py`
- **.test_create_team()** (2 connections) — `tests/test_teams.py`
- **.test_list_teams()** (2 connections) — `tests/test_teams.py`
- **With agents in the org, creating a manager-less team must fail.** (1 connections) — `tests/test_teams.py`
- **Test assigning agents to team.** (1 connections) — `tests/test_teams.py`
- **Supplying a valid manager satisfies the rule.** (1 connections) — `tests/test_teams.py`
- **A manager id that does not exist must not be accepted.** (1 connections) — `tests/test_teams.py`
- **Every team must have a manager.** (1 connections) — `tests/test_teams.py`
- **Test getting a single team.** (1 connections) — `tests/test_teams.py`
- **Test deleting a team.** (1 connections) — `tests/test_teams.py`

## Relationships

- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)

## Source Files

- `tests/test_teams.py`

## Audit Trail

- EXTRACTED: 27 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*