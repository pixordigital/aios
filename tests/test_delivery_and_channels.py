"""The inbound → agent → reply chain, and the automations that feed it.

Each defect here either lost a customer message, routed it to the wrong
tenant, or produced a green job for work that never happened.
"""

import hashlib
import inspect
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ─── delivery: a repeated reply was silently swallowed ─────────────────────

def test_idempotency_key_distinguishes_two_real_sends():
    """The key was sha256(conversation | text | hour). Two inbound messages in
    one hour whose agent reply was byte-identical produced the same key, so the
    pre-check dropped the second — no send, no error, no DLQ."""
    from aios.core.delivery import deliver_message

    src = inspect.getsource(deliver_message)
    assert "msg_id" in src, "the inbound message id is not part of the key"


# ─── DLQ replay could never succeed ───────────────────────────────────────

def test_dlq_replay_passes_args_positionally():
    """write_dlq stores {"args": [...], "kwargs": {...}} but retry did
    `enqueue_job(name, **payload)`, so arq got zero positional args and pushed
    "args"/"kwargs" in as keyword arguments. Every replay died on a TypeError
    while the row had already been marked `retried`."""
    from aios.core.dead_letter import retry_dlq

    src = inspect.getsource(retry_dlq)
    assert "payload.get(\"args\")" in src
    assert "enqueue_job(entry.job_name, **payload)" not in src, (
        "the whole payload dict is still splatted into the job as kwargs"
    )


def test_dlq_replay_marks_recovered_only_after_enqueue():
    from aios.core.dead_letter import retry_dlq

    src = inspect.getsource(retry_dlq)
    enqueue_at = src.index("enqueue_job")
    mark_at = src.index('status = "retried"')
    assert enqueue_at < mark_at, "the row is marked recovered before the job is queued"


# ─── a failed run looked like a successful job ─────────────────────────────

def test_failed_agent_run_retries_and_dead_letters():
    """AgentRuntime never raises, so a run that produced no answer fell through
    to `return`, set inbound_completed, and exited 0 — no retry, no DLQ entry,
    nothing for an operator to see."""
    src = (ROOT / "aios/tasks/jobs.py").read_text()
    block = src[src.index("if is_failed_run(reply_text):"):]
    block = block[: block.index("else:")]
    assert "raise" in block, "a failed run still returns quietly"


def test_limit_denial_and_stopped_team_reach_the_dlq():
    src = (ROOT / "aios/tasks/jobs.py").read_text()
    assert "org limit: " in src, "a quota denial is dropped without a DLQ entry"
    assert "every agent in the team is stopped" in src


# ─── channel lifecycle ────────────────────────────────────────────────────

def test_channel_toggle_and_create_start_the_adapter():
    """main.py started channels once during lifespan and nothing else did, so a
    channel created or re-enabled afterwards never opened its poll loop, and a
    disabled one kept polling and replying."""
    from aios.channels.manager import ChannelManager

    assert hasattr(ChannelManager, "sync"), "no way to start/stop an adapter on demand"
    for path in ("aios/api/channels.py", "aios/dashboard/app.py"):
        src = (ROOT / path).read_text()
        assert "_sync_channel" in src, f"{path} toggles the flag without syncing the adapter"


# ─── event triggers were creatable but inert ──────────────────────────────

def test_event_triggers_actually_fire():
    """fire_event_triggers existed with zero call sites, so every "event"
    trigger the dashboard could create was inert."""
    callers = []
    for p in ROOT.glob("aios/**/*.py"):
        if p.name == "automations.py":
            continue
        if "fire_event_triggers(" in p.read_text():
            callers.append(p.name)
    assert callers, "fire_event_triggers has no callers — event triggers never run"


# ─── web channel could not deliver ────────────────────────────────────────

@pytest.mark.asyncio
async def test_web_channel_send_returns_an_id():
    """send() returned None unconditionally and delivery.py treats None as
    "channel unavailable", so every web-chat reply was retried 3x and
    dead-lettered even though the agent had answered."""
    from aios.channels.base import OutboundMessage
    from aios.channels.web import WebChannel

    out = await WebChannel().send(OutboundMessage("c1", "oi", "conn-1"))
    assert out is not None, "still returns None → the reply is dead-lettered"


def test_web_chat_socket_endpoint_exists():
    """Nothing registered into WebChannel._connections and nothing called its
    handle_incoming, so the web channel had no transport at all."""
    assert hasattr(__import__("aios.channels.web", fromlist=["WebChannel"]).WebChannel, "attach")
    src = (ROOT / "aios/api/ws.py").read_text()
    assert '/ws/chat' in src, "no endpoint registers a web-chat socket"


def test_web_messages_carry_a_dedup_key():
    """jobs.py derives its dedup key from extra["msg_id"]; web messages had
    none, so every one looked new and could be answered twice."""
    from aios.channels.web import WebChannel

    src = inspect.getsource(WebChannel.handle_incoming)
    assert "msg_id" in src


# ─── tenant isolation on inbound webhooks ─────────────────────────────────

def test_email_and_voice_webhooks_do_not_pick_an_arbitrary_tenant():
    """Both did `select(ChannelConnection).where(type==..., is_active)
    .scalars().first()` with no org filter and no tenant identity in the
    payload, so with two tenants every inbound mail/call went to whichever row
    came first — wrong agent, wrong budget, wrong org_id."""
    for path in ("aios/api/email_webhook.py", "aios/api/voice_webhook.py"):
        src = (ROOT / path).read_text()
        assert "more than one active" in src, (
            f"{path} still auto-resolves one connection across all tenants"
        )


def test_email_reply_is_addressed_to_the_sender():
    """`to = self._config.get("last_from", "") or email_addr` — last_from is
    written nowhere, so every reply went to the agent's own mailbox and the
    customer never received it."""
    from aios.channels.email_ import EmailChannel

    src = inspect.getsource(EmailChannel.send)
    assert "from_email" in src or 'extra.get("from")' in src
    assert 'or email_addr\n            msg["To"] = to' not in src


# ─── two pollers per mailbox ──────────────────────────────────────────────

def test_only_one_poller_per_mailbox_or_bot_token():
    """gunicorn runs --workers 2 and the lifespan runs per worker, so email and
    Telegram each started two long-pollers against the same account."""
    for path, marker in (
        ("aios/channels/email_.py", "_claim_mailbox"),
        ("aios/channels/telegram.py", "aios:telegram-poll"),
    ):
        assert marker in (ROOT / path).read_text(), f"{path} has no poll lease"


# ─── workflow tool nodes ──────────────────────────────────────────────────

def test_workflow_reads_org_before_building_the_tool_engine():
    """The ToolEngine line read `org` one statement before it was assigned, so
    every tool node in every workflow raised UnboundLocalError."""
    from aios.core.workflow import WorkflowEngine

    src = inspect.getsource(WorkflowEngine)
    assert src.index('org = shared.get("org_id")') < src.index("ToolEngine([node.tool_name]")


# ─── guard deferrals could loop forever ───────────────────────────────────

def test_guard_deferral_counts_and_eventually_dead_letters():
    """The defer re-enqueued with the same `attempt`, so a guard block that did
    not clear inside 30s retried forever: no DLQ, no signal, no _MAX_RETRIES."""
    from aios.core.delivery import _MAX_DEFERS, deliver_message

    assert _MAX_DEFERS > 0
    src = inspect.getsource(deliver_message)
    assert "attempt + 1" in src, "the defer still passes `attempt` unchanged"


# ─── voice ────────────────────────────────────────────────────────────────

def test_voice_ack_does_not_repeat_the_caller():
    """The bridge synthesised the INBOUND text and returned it, so a caller
    heard themselves back instead of the agent."""
    src = (ROOT / "aios/api/voice.py").read_text()
    ack = src[src.index("synthesize("):]
    ack = ack[: ack.index("return {")]
    assert "text[:500]" not in ack, "the ack still synthesises the caller's words"


def test_voice_stt_is_not_configured_by_default():
    """voice_stt_url defaulted to a host that only exists under an opt-in
    compose profile, so VoiceChannel.test() claimed "+ STT configurado" and
    every transcription failed on DNS."""
    from aios.config import settings

    assert settings.voice_stt_url == "", "STT still points at a service that is not running"


def test_voice_call_meters_a_queued_call():
    """cost was 0.02 only when status == 'dialing', but place_call returns
    'queued' and flips later, so voice minutes were never billed."""
    src = (ROOT / "aios/tools/voice_call.py").read_text()
    assert 'res.get("status") == "dialing"' not in src, (
        "cost still keys off a status the tool never sees"
    )


# ─── flow editor offered tools that do not exist ──────────────────────────

def test_flow_palette_only_offers_real_tools():
    import aios.tools  # noqa: F401
    from aios.tools.registry import TOOL_REGISTRY

    src = (ROOT / "aios/dashboard/templates/flow_editor.html").read_text()
    import re

    offered = set(re.findall(r'data-tool="([\w_]+)"', src))
    missing = sorted(offered - set(TOOL_REGISTRY))
    assert not missing, f"flow palette offers unregistered tools: {missing}"

# ─── inbound email died on a NameError before dispatching ─────────────────

async def test_inbound_email_dispatches_to_the_explicit_channel(
    test_session, test_org, monkeypatch
):
    """_process_inbound_email read `body`, which only exists in its *caller's*
    scope -- the payload parameter is `email_data`. Every inbound email raised
    NameError, so the tenant-selection code directly below it (added to stop
    tenant B's mail being answered by tenant A's agent) had never run once."""
    from contextlib import asynccontextmanager

    from aios.db.models import ChannelConnection

    conn = ChannelConnection(
        channel_type="email",
        label="inbox",
        config={},
        is_active=True,
        org_id=test_org.id,
    )
    test_session.add(conn)
    await test_session.commit()

    @asynccontextmanager
    async def fake_db_session():
        yield test_session

    monkeypatch.setattr("aios.db.backend.db_session", fake_db_session)

    seen: list[dict] = []

    async def fake_dispatch(**kw):
        seen.append(kw)

    monkeypatch.setattr("aios.core.dispatch.dispatch_inbound", fake_dispatch)

    from aios.api.email_webhook import _process_inbound_email

    out = await _process_inbound_email(
        {"from": "buyer@example.com", "channel_id": str(conn.id)}, "sendgrid"
    )

    assert len(seen) == 1, f"the explicit channel_id did not reach dispatch_inbound (got {seen})"
    assert seen[0]["channel_connection_id"] == str(conn.id)


async def test_inbound_email_refuses_to_guess_between_two_mailboxes(
    test_session, test_org, monkeypatch
):
    """Auto-resolution is only safe while it is unambiguous. Two active email
    connections and no channel_id must be refused, not resolved to whichever
    row the database happened to return first."""
    from contextlib import asynccontextmanager

    from aios.db.models import ChannelConnection

    for label in ("inbox-a", "inbox-b"):
        test_session.add(
            ChannelConnection(
                channel_type="email",
                label=label,
                config={},
                is_active=True,
                org_id=test_org.id,
            )
        )
    await test_session.commit()

    @asynccontextmanager
    async def fake_db_session():
        yield test_session

    monkeypatch.setattr("aios.db.backend.db_session", fake_db_session)

    async def fake_dispatch(**kw):
        raise AssertionError("dispatched an ambiguous inbound email")

    monkeypatch.setattr("aios.core.dispatch.dispatch_inbound", fake_dispatch)

    from aios.api.email_webhook import _process_inbound_email

    out = await _process_inbound_email({"from": "buyer@example.com"}, "sendgrid")

    assert out.get("ok") is False, out
