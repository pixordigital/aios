"""REST conversation turns run in the worker, not inside the request."""

import pytest
import pytest_asyncio
from sqlalchemy import select

from aios.db.models import Agent, Conversation, Message


@pytest_asyncio.fixture(loop_scope="function")
async def agent_conv(test_db_session, test_org):
    agent = Agent(
        org_id=test_org.id,
        name="Turn Agent",
        agent_type="custom",
        llm_config={"model": "test/model"},
        system_prompt="p",
        tools=[],
        governance_config={},
    )
    test_db_session.add(agent)
    await test_db_session.commit()
    await test_db_session.refresh(agent)

    conv = Conversation(org_id=test_org.id, channel="web", agent_id=agent.id)
    test_db_session.add(conv)
    await test_db_session.commit()
    await test_db_session.refresh(conv)
    return agent, conv


async def _user_message(session, conv, org_id, text="hello"):
    msg = Message(conversation_id=conv.id, org_id=org_id, role="user", content=text)
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


@pytest.mark.asyncio(loop_scope="function")
async def test_send_message_enqueues_instead_of_running(auth_client, monkeypatch):
    seen = {}

    async def fake_enqueue(name, payload, **kw):
        seen["name"] = name
        seen["payload"] = payload
        return object()

    def _no_runtime(*a, **kw):
        raise AssertionError("the API request ran the agent inline")

    monkeypatch.setattr("aios.tasks.queue.enqueue_task", fake_enqueue)
    monkeypatch.setattr("aios.core.agent.AgentRuntime", _no_runtime)

    created = await auth_client.post("/api/conversations", json={"channel": "web"})
    conv_id = created.json()["id"]
    response = await auth_client.post(
        f"/api/conversations/{conv_id}/messages", json={"content": "Hello"}
    )

    assert response.status_code == 200
    assert response.json()["reply"] is None
    assert seen["name"] == "aios.tasks.jobs.conversation_turn_job"
    assert seen["payload"]["conversation_id"] == conv_id
    assert seen["payload"]["text"] == "Hello"


def _fake_runtime(persists: bool, reply: str = "hi there"):
    class _Runtime:
        def __init__(self, agent, *a, **kw):
            self.agent = agent

        async def run(self, conversation_id, text, db=None):
            if persists:
                db.add(
                    Message(
                        conversation_id=conversation_id,
                        org_id=self.agent.org_id,
                        role="assistant",
                        content=reply,
                        agent_id=self.agent.id,
                    )
                )
                await db.commit()
            return reply

    return _Runtime


async def _run_turn(session, agent, conv, msg):
    from aios.tasks.jobs import conversation_turn_job

    return await conversation_turn_job(
        None,
        {
            "message_id": msg.id,
            "conversation_id": conv.id,
            "text": msg.content,
            "org_id": agent.org_id,
        },
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_turn_is_idempotent_and_does_not_duplicate_the_reply(
    test_db_session, test_org, agent_conv, monkeypatch
):
    agent, conv = agent_conv
    monkeypatch.setattr("aios.core.agent.AgentRuntime", _fake_runtime(persists=True))
    msg = await _user_message(test_db_session, conv, test_org.id)

    assert await _run_turn(test_db_session, agent, conv, msg) == {"ok": True}
    # ARQ retry of the same job must not run or write again.
    assert await _run_turn(test_db_session, agent, conv, msg) == {"skipped": "already done"}

    rows = (
        await test_db_session.execute(
            select(Message).where(
                Message.conversation_id == conv.id, Message.role == "assistant"
            )
        )
    ).scalars().all()
    assert len(rows) == 1, "runtime row was duplicated by the job"


@pytest.mark.asyncio(loop_scope="function")
async def test_turn_writes_reply_when_runtime_did_not(
    test_db_session, test_org, agent_conv, monkeypatch
):
    agent, conv = agent_conv
    monkeypatch.setattr("aios.core.agent.AgentRuntime", _fake_runtime(persists=False))
    msg = await _user_message(test_db_session, conv, test_org.id)

    assert await _run_turn(test_db_session, agent, conv, msg) == {"ok": True}

    rows = (
        await test_db_session.execute(
            select(Message).where(
                Message.conversation_id == conv.id, Message.role == "assistant"
            )
        )
    ).scalars().all()
    assert [r.content for r in rows] == ["hi there"]
