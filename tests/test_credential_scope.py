"""Credential scope resolver: explicit allow, fail closed on mismatch."""

import pytest_asyncio

from aios.core.credential_scope import resolve_scoped_credential
from aios.db.models import Agent, Credential, CredentialScope, Team, team_agents


@pytest_asyncio.fixture
async def seed(test_session, test_org):
    agent = Agent(org_id=test_org.id, name="scope-agent")
    cred = Credential(org_id=test_org.id, name="key", cred_type="bearer", data_enc="")
    test_session.add_all([agent, cred])
    await test_session.commit()
    await test_session.refresh(agent)
    await test_session.refresh(cred)
    return test_org, agent, cred


async def _add_scope(sess, cred, org_id, scope_type, scope_id):
    sess.add(
        CredentialScope(
            org_id=org_id,
            credential_id=cred.id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    )
    await sess.commit()


async def _resolve(sess, cred, org_id, agent_id="some-agent", tool_name="http_request"):
    return await resolve_scoped_credential(
        sess, cred.id, org_id=org_id, agent_id=agent_id, tool_name=tool_name
    )


async def test_no_scope_rows_legacy_allow(test_session, seed):
    org, agent, cred = seed
    assert await _resolve(test_session, cred, org.id, agent.id) is cred


async def test_agent_scope_allow(test_session, seed):
    org, agent, cred = seed
    await _add_scope(test_session, cred, org.id, "agent", agent.id)
    assert await _resolve(test_session, cred, org.id, agent.id) is cred


async def test_tool_scope_allow(test_session, seed):
    org, agent, cred = seed
    await _add_scope(test_session, cred, org.id, "tool", "http_request")
    assert await _resolve(test_session, cred, org.id, agent.id) is cred


async def test_team_scope_allow(test_session, seed):
    org, agent, cred = seed
    team = Team(org_id=org.id, name="scope-team")
    test_session.add(team)
    await test_session.flush()
    await test_session.execute(
        team_agents.insert().values(team_id=team.id, agent_id=agent.id)
    )
    await _add_scope(test_session, cred, org.id, "team", team.id)

    outsider = Agent(org_id=org.id, name="outsider")
    test_session.add(outsider)
    await test_session.commit()
    await test_session.refresh(outsider)

    assert await _resolve(test_session, cred, org.id, agent.id) is cred
    assert await _resolve(test_session, cred, org.id, outsider.id) is None


async def test_scope_mismatch_and_malformed_deny(test_session, seed):
    org, agent, cred = seed
    await _add_scope(test_session, cred, org.id, "agent", agent.id)
    assert await _resolve(test_session, cred, org.id, "other-agent") is None
    assert await _resolve(test_session, cred, org.id, agent.id, "hubspot") is cred
    assert await resolve_scoped_credential(
        test_session, "missing-id", org_id=org.id, agent_id=agent.id, tool_name="http_request"
    ) is None

    malformed = Credential(org_id=org.id, name="bad", cred_type="bearer", data_enc="")
    test_session.add(malformed)
    await test_session.flush()
    await _add_scope(test_session, malformed, org.id, "superuser", agent.id)
    assert await _resolve(test_session, malformed, org.id, agent.id) is None


async def test_cross_org_deny(test_session, seed, second_org):
    org, agent, cred = seed
    await _add_scope(test_session, cred, org.id, "agent", agent.id)
    assert await _resolve(test_session, cred, second_org.id, agent.id) is None

    foreign_scoped = Credential(org_id=org.id, name="foreign", cred_type="bearer", data_enc="")
    test_session.add(foreign_scoped)
    await test_session.flush()
    await _add_scope(test_session, foreign_scoped, second_org.id, "tool", "http_request")
    assert await _resolve(test_session, foreign_scoped, org.id, agent.id) is None


async def test_missing_context_with_scope_rows_deny(test_session, seed):
    org, agent, cred = seed
    await _add_scope(test_session, cred, org.id, "agent", agent.id)
    assert await _resolve(test_session, cred, org.id, "") is None
    assert await _resolve(test_session, cred, org.id, agent.id, "") is None
    assert await _resolve(test_session, cred, "", agent.id) is None


async def test_missing_org_denies_even_without_scope_rows(test_session, seed):
    org, agent, cred = seed
    assert await resolve_scoped_credential(
        test_session, cred.id, org_id="", agent_id=agent.id, tool_name="http_request"
    ) is None
    assert await _resolve(test_session, cred, org.id, agent.id) is cred
