"""Regression tests for the agent/WhatsApp blockers found in the audit.

Each test names the failure it prevents, because every one of these was a
silent no-op that a green suite did not catch.
"""

import json
import re

import pytest


class TestAgentRuntimeIsNotAmputated:
    """`is_failed_run` was inserted at module level inside the class body.

    The dedent terminated `AgentRuntime`, so `run_stream` and five siblings
    became nested functions of `is_failed_run`. Every agent run — streaming or
    not — raised AttributeError, and AutonomousAgent swallowed it into a
    "⏸️ [HITL] Não consegui resolver" message to the customer.
    """

    def test_public_methods_exist(self):
        from aios.core.agent import AgentRuntime

        for name in (
            "run",
            "run_stream",
            "run_structured",
            "build_context",
            "_build_context",
            "_spawn_subagent",
            "load_project_skills",
        ):
            assert hasattr(AgentRuntime, name), f"AgentRuntime.{name} is gone"

    def test_is_failed_run_is_module_level(self):
        import aios.core.agent as mod

        assert callable(mod.is_failed_run)
        assert mod.is_failed_run("") is True
        assert mod.is_failed_run("   ") is True
        assert mod.is_failed_run("I'm having trouble completing this request.") is True
        assert mod.is_failed_run("⏸️ [HITL] aguardo humano") is True
        assert mod.is_failed_run("Seu pedido saiu hoje.") is False


class TestMessagesCarryOrgId:
    """messages.org_id is a non-nullable FK.

    The runtime built `Message(...)` without it, so the first commit raised
    IntegrityError and — with no rollback() on the backend — left the caller's
    session in PendingRollbackError. The reply was never stored, never
    delivered, and retried into the DLQ.
    """

    def test_every_message_construction_sets_org_id(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "aios"
        offenders = []
        # `conversation_id=` and `role=` in the same argument list is the
        # Message constructor's signature; matching on either alone also catches
        # HookContext(... agent_id=..., conversation_id=...) blocks.
        call = re.compile(
            r"\b_?M(?:sg|essage)\(\s*\n((?:\s+.*\n)+?)\s*\)"
        )
        for path in root.rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            for m in call.finditer(src):
                body = m.group(1)
                if "conversation_id=" in body and "role=" in body and "org_id" not in body:
                    line = src[: m.start()].count("\n") + 1
                    offenders.append(f"{path.name}:{line}")
        assert not offenders, f"Message() without org_id at {offenders}"

    def test_backend_exposes_rollback(self):
        from aios.db.backend import DatabaseBackend
        from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend

        assert hasattr(DatabaseBackend, "rollback")
        assert hasattr(SQLAlchemyBackend, "rollback")


class TestRunGateIsSpendOnly:
    """check_org_limits is the per-run gate, not the create gate.

    It also checked max_agents / max_teams, which are resource-count quotas.
    Once an org reached its agent quota, every run of its own already-deployed
    agents was denied — one org, zero replies.
    """

    async def test_resource_counts_do_not_gate_a_run(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_limits_locking import _FakeDB, _Stop

        from aios.core import limits

        db = _FakeDB("postgresql")
        with pytest.raises(_Stop):
            await limits.check_org_limits("org-1", db)

        selects = [s for s in db.statements if s.lstrip().upper().startswith("SELECT")]
        assert not any("FROM agents" in s for s in selects), "agent quota still gates runs"
        assert not any("FROM teams" in s for s in selects), "team quota still gates runs"
        # The spend lock is the part that belongs here.
        assert any("FOR UPDATE" in s for s in selects), selects


class TestGuardSendIsNotDoubleCounted:
    """guard_send was called by the delivery layer and again by the channel.

    It writes `_last_text` and then reads it back through is_duplicate, so the
    second call always saw its own write and returned "duplicate 5min" —
    `_send_baileys` returned None before any HTTP call, and delivery retried
    three times into the DLQ. Effectively every agent reply was dropped.
    """

    async def test_precheck_does_not_block_the_send_it_precedes(self):
        from aios.core import whatsapp_guard as g

        to = "5511999999999"
        assert await g.guard_send(to, "Olá!", provider="meta", record=False) == (True, "")

    async def test_the_recording_call_succeeds_after_a_precheck(self):
        from aios.core import whatsapp_guard as g

        to = "5511999999998"
        assert await g.guard_send(to, "Olá!", provider="meta", record=False) == (True, "")
        assert await g.guard_send(to, "Olá!", provider="evolution", instance="i1") == (
            True,
            "",
        )

    async def test_a_genuine_repeat_is_still_suppressed(self):
        """The feature the double call was accidentally providing."""
        from aios.core import whatsapp_guard as g

        to = "5511999999997"
        await g.guard_send(to, "Seu pedido saiu", provider="evolution", instance="i2")
        assert await g.guard_send(
            to, "Seu pedido saiu", provider="evolution", instance="i2", record=False
        ) == (False, "duplicate 5min")

    async def test_a_send_counts_once_toward_the_rate_limit(self):
        from aios.core import whatsapp_guard as g

        to = "5511999999996"
        await g.guard_send(to, "oi", provider="meta", record=False)
        await g.guard_send(to, "oi", provider="evolution", instance="i3")
        assert len(g._contact_queues[to]) == 1
        assert len(g._global_daily["i3"]) == 1


class TestWebhookAuthUsesTheDecryptedKey:
    """Channels created via the dashboard store `enc:<fernet>`.

    The webhook compared the header against the raw config value, so auth
    failed for every dashboard-created channel while API-created ones worked —
    the one path the tests exercised.
    """

    def test_ciphertext_is_not_the_secret(self):
        from aios.api.evolution_webhook import _channel_api_key
        from aios.core.secrets import encrypt_channel_config
        from aios.db.models import ChannelConnection

        secret = "whatsapp-secret-do-not-log"
        ch = ChannelConnection(
            org_id="o1",
            label="l",
            channel_type="evolution",
            config=encrypt_channel_config({"instance": "i1", "api_key": secret}),
        )
        assert _channel_api_key(ch) == secret
        assert not _channel_api_key(ch).startswith("enc:")

    def test_plaintext_key_still_works(self):
        from aios.api.evolution_webhook import _channel_api_key
        from aios.db.models import ChannelConnection

        ch = ChannelConnection(
            org_id="o1",
            label="l",
            channel_type="evolution",
            config={"instance": "i1", "api_key": "plain"},
        )
        assert _channel_api_key(ch) == "plain"

    def test_missing_key_is_empty(self):
        from aios.api.evolution_webhook import _channel_api_key
        from aios.db.models import ChannelConnection

        ch = ChannelConnection(
            org_id="o1", label="l", channel_type="evolution", config={"instance": "i1"}
        )
        assert _channel_api_key(ch) == ""


class TestEvolutionEnvPrefix:
    """Settings uses env_prefix="AIOS_".

    Compose exported bare EVOLUTION_API_KEY / EVOLUTION_SERVER_URL, so
    settings.evolution_api_key was "" in the running container and every
    Evolution call went out with an empty credential.
    """

    def test_compose_uses_the_aios_prefix(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for name in ("docker-compose.coolify.yml", "docker-compose.yaml"):
            src = (root / name).read_text(encoding="utf-8")
            # The Evolution *service* still reads the bare name — that is its
            # own AUTHENTICATION_API_KEY contract, not a Settings field. Any
            # other service must carry the AIOS_ prefix, so track which service
            # block each line belongs to and flag the bare name outside it.
            service = None
            for line in src.splitlines():
                m = re.match(r"^ {4}([\w-]+):\s*$", line) or re.match(
                    r"^ {2}([\w-]+):\s*$", line
                )
                if m:
                    service = m.group(1)
                    continue
                stripped = line.strip()
                if service == "evolution":
                    continue
                if stripped.startswith(("EVOLUTION_API_KEY:", "EVOLUTION_SERVER_URL:")):
                    raise AssertionError(
                        f"{name}: service {service!r} sets {stripped!r} without the "
                        f"AIOS_ prefix (Settings uses env_prefix='AIOS_')"
                    )


class TestWebhookSetMatchesEvolutionSchema:
    """Instance creation never pointed Evolution back at AIOS usably.

    `evo_create_instance` set no webhook at all, so every instance made through
    the dashboard wizard, /lojista/create or the evolution page could send but
    never received. The one call site that did set one used option keys
    Evolution does not recognise.
    """

    async def test_body_matches_the_evolution_schema(self, monkeypatch):
        """Verified against the running evoapicloud/evolution-api:v2.3.7.

        A flat body is rejected with 400. The option keys are `byEvents` and
        `base64`; `webhookByEvents` / `webhookBase64` are not in the schema and
        are dropped without complaint.
        """
        import aios.core.evolution_api as evo

        seen = {}

        class _Resp:
            status_code = 201
            text = ""

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                seen["url"] = url
                seen["headers"] = headers
                seen["body"] = json
                return _Resp()

        monkeypatch.setattr(evo.httpx, "AsyncClient", lambda *a, **k: _Client())

        res = await evo.evo_set_webhook("inst1", api_key="s3cret")
        assert res["ok"] is True
        body = seen["body"]
        assert "webhook" in body, "Evolution 2.3.7 requires a top-level `webhook` object"
        wh = body["webhook"]
        assert wh["enabled"] is True
        assert wh["url"].endswith("/inst1")
        assert "MESSAGES_UPSERT" in wh["events"]
        assert wh["headers"]["x-webhook-auth"] == "s3cret"
        # The schema's option key names, not the ones Evolution ignores.
        assert "byEvents" in wh and "base64" in wh
        assert "webhookByEvents" not in wh and "webhookBase64" not in wh
        assert seen["headers"]["apikey"] == "s3cret"


def _strip_comments(src: str) -> str:
    """Remove # comments and docstring bodies, leaving executable lines."""
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    return "\n".join(line.split("#")[0] for line in src.splitlines())


class TestInboxJsonFiltersCompile:
    """`.astext` is JSONB-on-Postgres only.

    `extra_data` is a generic sqlalchemy.JSON, so every inbox filter with a
    status/assignment/search raised AttributeError and the screen 500'd.
    """

    def test_filters_build_on_sqlite(self):
        from sqlalchemy import select
        from sqlalchemy.dialects import sqlite

        from aios.api.inbox import _json_str
        from aios.db.models import Conversation

        for cond in (
            _json_str(Conversation, "status") == "closed",
            _json_str(Conversation, "status") != "closed",
            _json_str(Conversation, "assigned_to") == "u1",
            _json_str(Conversation, "contact_name").ilike("%acme%"),
        ):
            select(Conversation).where(cond).compile(dialect=sqlite.dialect())

    def test_no_astext_anywhere_in_the_api(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "aios"
        # Code only, not comments — a comment naming the accessor is fine, a
        # call to it raises at query-build time.
        offenders = [
            p.name
            for p in root.rglob("*.py")
            if re.search(r"\.astext\b", _strip_comments(p.read_text(encoding="utf-8")))
        ]
        assert not offenders, f".astext still called in {offenders}"


class TestCacheIsOrgScoped:
    """The caches are process-global and were keyed without the org.

    Org A's `sql_query` result for a given SQL string was served to org B.
    """

    def test_tool_cache_does_not_cross_tenants(self):
        from aios.core.cache import ToolResultCache

        c = ToolResultCache()
        c.set("sql_query", "SELECT * FROM deals", "org-a rows", scope="org-a")
        assert c.get("sql_query", "SELECT * FROM deals", scope="org-a") == "org-a rows"
        assert c.get("sql_query", "SELECT * FROM deals", scope="org-b") is None

    def test_response_cache_does_not_cross_tenants(self):
        from aios.core.cache import ResponseCache

        c = ResponseCache()
        msgs = [{"role": "user", "content": "hi"}]
        c.set(msgs, "openai/gpt-4o", 0.7, {"content": "org-a"}, None, scope="org-a")
        assert c.get(msgs, "openai/gpt-4o", 0.7, None, scope="org-b") is None
        assert c.get(msgs, "openai/gpt-4o", 0.7, None, scope="org-a") == {"content": "org-a"}


class TestNonIdempotentToolsAreNotRetried:
    """execute() retried every exception three times.

    `send_email` that succeeded with a lost response sent three emails;
    `crm_create_deal` created three deals.
    """

    async def test_send_email_runs_once(self, monkeypatch):
        from aios.core import tools as tools_mod

        calls = []

        class _SendEmail:
            async def run(self, **kw):
                calls.append(kw)
                raise RuntimeError("connection reset after send")

        engine = tools_mod.ToolEngine([], org_id="o1")
        engine.tools = {"send_email": _SendEmail()}
        monkeypatch.setattr(tools_mod, "_TOOL_TIMEOUT", 5.0)
        with pytest.raises(tools_mod.ToolExecutionError):
            await engine.execute("send_email", json.dumps({"to": "a@b.c"}))
        assert len(calls) == 1, f"send_email ran {len(calls)} times"

    async def test_a_read_only_tool_is_still_retried(self, monkeypatch):
        from aios.core import tools as tools_mod

        calls = []

        class _Flaky:
            async def run(self, **kw):
                calls.append(kw)
                if len(calls) < 2:
                    raise RuntimeError("transient")
                return "ok"

        engine = tools_mod.ToolEngine([], org_id="o1")
        engine.tools = {"web_search": _Flaky()}
        monkeypatch.setattr(tools_mod, "_TOOL_TIMEOUT", 5.0)
        # Real sleep, 0.5s between attempts: patching asyncio.sleep through
        # tools_mod patches the stdlib module and recurses.
        out = await engine.execute("web_search", "{}")
        assert out == "ok"
        assert len(calls) == 2


class TestStreamRetryDoesNotReplay:
    """`started` was set and never read.

    A stream that failed after emitting tokens was retried from the start, so
    the caller received the prefix twice and any tool call in it ran twice.
    """

    async def test_midstream_failure_does_not_replay_the_prefix(self):
        import httpx

        from aios.core.providers import STREAM_ERROR, STREAM_TOKEN, LLMProvider

        class _Flaky(LLMProvider):
            def __init__(self):
                self.calls = 0

            async def chat(self, *a, **k):  # pragma: no cover - unused here
                raise NotImplementedError

            async def chat_stream(self, *a, **k):
                self.calls += 1
                yield {"type": STREAM_TOKEN, "content": "par"}
                raise httpx.ReadError("dropped")

            async def start(self): ...
            async def stop(self): ...

        p = _Flaky()
        got = [
            ev
            async for ev in p.chat_stream_retry(messages=[], model="openai/gpt-4o")
        ]
        assert p.calls == 1, "partial stream was replayed"
        tokens = [e for e in got if e["type"] == STREAM_TOKEN]
        assert len(tokens) == 1
        assert any(e["type"] == STREAM_ERROR for e in got)

    async def test_prestream_failure_is_still_retried(self):
        """The retry is still correct when nothing was emitted yet."""
        import httpx

        from aios.core.providers import STREAM_TOKEN, LLMProvider

        class _Flaky(LLMProvider):
            def __init__(self):
                self.calls = 0

            async def chat(self, *a, **k):  # pragma: no cover
                raise NotImplementedError

            async def chat_stream(self, *a, **k):
                self.calls += 1
                if self.calls == 1:
                    # Must be one of _RETRYABLE_ERRORS; a bare ConnectionError
                    # is not, and would exercise the wrong branch.
                    raise httpx.ConnectError("refused")
                yield {"type": STREAM_TOKEN, "content": "ok"}

            async def start(self): ...
            async def stop(self): ...

        p = _Flaky()
        got = [
            ev
            async for ev in p.chat_stream_retry(messages=[], model="openai/gpt-4o")
        ]
        assert p.calls == 2
        assert any(e["type"] == STREAM_TOKEN for e in got)


class TestSchedulerBookkeeping:
    """Three defects, all silent.

    1. `enqueue` fired an `agent_run` ARQ job with no `text`, so the agent
       ran on an empty user message — once per agent per team message.
    2. `AgentInstance(org_id="")` is a foreign-key violation on Postgres,
       hidden by a bare except.
    3. `start()` refused at capacity but the caller ran anyway, so
       max_concurrent was never enforced.
    """

    def test_enqueue_does_not_dispatch_a_job(self):
        import inspect

        from aios.core.scheduler import AgentScheduler

        src = inspect.getsource(AgentScheduler.enqueue)
        assert "enqueue_task" not in src, "enqueue still dispatches an agent_run job"

    async def test_no_instance_row_without_an_org(self):
        from aios.core.scheduler import scheduler

        n = await scheduler._persist_instance("a1", "", "c1", "queued")
        assert n is None

    def test_capacity_refusal_leaves_the_process_queued(self):
        from aios.core.scheduler import AgentScheduler, AgentState

        s = AgentScheduler()
        s._max_concurrent = 0
        s.enqueue("a1", conv_id="c1", org_id="o1")
        assert s.start("a1") is None
        assert s.get_process("a1").state == AgentState.QUEUED
        # And the counter must not drift below the real concurrency.
        s.terminate("a1")
        assert s.running_count() == 0


class TestOrchestratorRoutingClamps:
    def test_negative_index_from_the_llm_is_clamped(self):
        import inspect

        from aios.core.orchestrator import TeamOrchestrator

        src = _strip_comments(inspect.getsource(TeamOrchestrator._supervisor_route_stream))
        assert "max(0, min(" in src, "agent_index is not clamped at the low end"

    def test_hierarchical_stream_uses_a_runtime(self):
        import inspect

        from aios.core.orchestrator import TeamOrchestrator

        src = _strip_comments(inspect.getsource(TeamOrchestrator._hierarchical_route_stream))
        assert "agent.run_stream(" not in src, "calling run_stream on the ORM model"
        assert "rt.run_stream(" in src


class TestAgentGovernanceIsPersisted:
    """create_agent never passed governance_config to the model.

    Every reader defaults `gov.get("autonomous", True)` to True, so a client
    that POSTed {"autonomous": false} silently got an autonomous HITL agent.
    """

    def test_create_agent_passes_governance_config(self):
        import inspect

        from aios.api.agents import create_agent

        assert "governance_config=body.governance_config" in inspect.getsource(create_agent)


class TestApprovalIsDecidableAcrossProcesses:
    """The approval store was an in-process dict plus an asyncio.Event.

    The API process serves /approve; the ARQ worker holds the run. The event
    could never be set from the other side, so every approval timed out after
    the full 300s window with the agent blocked the whole time.
    """

    def test_approve_is_awaitable(self):
        import inspect

        from aios.core.approval import ApprovalManager

        assert inspect.iscoroutinefunction(ApprovalManager.approve)
        assert inspect.iscoroutinefunction(ApprovalManager.reject)

    def test_pending_action_row_carries_the_org(self):
        import inspect

        from aios.core.approval import ApprovalManager

        src = inspect.getsource(ApprovalManager.request_approval)
        assert "org_id=org_id" in src, "approval row not org-scoped"

    def test_waiter_polls_the_db(self):
        import inspect

        from aios.core.approval import ApprovalManager

        assert "_db_status" in inspect.getsource(ApprovalManager._wait)
