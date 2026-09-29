"""Reply persistence for team-bound channels.

Regression: jobs.py wrote Team.id into messages.agent_id, which is a FK to
agents.id. Every team-bound Slack channel died with
ForeignKeyViolationError: messages_agent_id_fkey on the reply insert.
"""

from aios.tasks.jobs import _reply_meta


class _FakeAgent:
    id = "agent-123"


class _FakeTeam:
    """Duck-type check target: must look like a Team, not an Agent."""

    id = "team-456"
    agents = []

    def __repr__(self):
        return "<Team>"


def test_team_does_not_write_team_id_into_agent_id():
    from aios.db.models import Team

    team = Team(id="team-456", org_id="org-1", name="sales")
    meta = _reply_meta(team)
    assert meta["agent_id"] is None, "Team.id must never go into messages.agent_id"
    assert meta["extra_data"].get("team_id") == "team-456"


def test_agent_still_writes_its_own_id():
    from aios.db.models import Agent

    agent = Agent(id="agent-123", org_id="org-1", name="sales-sdr", agent_type="sdr")
    meta = _reply_meta(agent)
    assert meta["agent_id"] == "agent-123"
    assert not meta["extra_data"]


def test_message_kwargs_are_acceptable():
    """Both branches must produce kwargs Message() actually accepts."""
    from aios.db.models import Agent, Message, Team

    cols = {c.name for c in Message.__table__.columns}
    for obj in (Team(id="t", org_id="o", name="n"), Agent(id="a", org_id="o", name="n", agent_type="custom")):
        keys = set(_reply_meta(obj))
        assert keys <= cols, f"{keys - cols} are not columns on Message"
