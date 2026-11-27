"""Agent runtime — think → act → observe → respond loop.

Uses syscall layer for all kernel interactions (LLM, memory, tools).
Agent scheduler manages queue and lifecycle.
"""

import asyncio
import json
import logging
import uuid

from typing import AsyncGenerator
from aios.config import settings
from aios.db.backend import DatabaseBackend

from aios.core.cache import cache, tool_cache
from aios.core.context_manager import context_manager
from aios.core.hooks import HookContext, HookPoint, hooks
from aios.core.memory import MemoryManager
from aios.core.providers import get_provider
from aios.core.providers import (
    STREAM_TOKEN, STREAM_DONE, STREAM_ERROR, STREAM_TOOL_CALL,
)
from aios.core import router
from aios.core.action_policy import classify_tool_action
from aios.core.router import floor_from_extra, route, should_escalate, model_runtime_eligible
from aios.core.scheduler import scheduler
from aios.core.syscalls import (
    SyscallRequest, SyscallResponse, SyscallType,
    dispatcher as syscall_dispatcher,
)
from aios.core.tools import ToolEngine
from aios.core.tracing import start_span, end_span
from aios.db.models import Agent as AgentModel
from aios.db.models import Message

logger = logging.getLogger(__name__)

# An agent run does not raise when it fails: AgentRuntime returns a canned
# apology and AutonomousAgent returns a reflection/HITL string. Anything that
# publishes a run's output to a human must screen these out, or a failed
# evaluation loop gets delivered as if it were the answer.
#
# Defined above AgentRuntime, not below it: orchestrator.py imports this at
# module level, and the agent<->orchestrator import cycle means orchestrator can
# run while this module is only half-executed. Below the class it would not
# exist yet and the import would fail with ImportError.
_FAILED_RUN_MARKERS = (
    "I'm having trouble completing this request",
    "Não consegui",
    "Falha após 3 tentativas",
    "Falha: ",
    "⏸️ [HITL]",
)


def is_failed_run(text: str) -> bool:
    """True when `text` is a runtime failure notice, not a real answer."""
    if not text or not text.strip():
        return True
    return any(marker in text for marker in _FAILED_RUN_MARKERS)

# ponytail: prefix → context window; upgrade when model catalog grows
_CTX_MAP = {
    "openai/gpt-4o": 128_000,
    "openai/gpt-4": 128_000,
    "openai/o3": 200_000,
    "openai/o1": 200_000,
    "anthropic": 200_000,
    "anthropic-direct": 200_000,
    "google/gemini": 1_000_000,
    "opencode/": 128_000,
    "ollama/": 32_768,
}


def _ctx_window(model: str) -> int:
    for prefix, window in _CTX_MAP.items():
        if model.startswith(prefix):
            return window
    return 32_000


# Tool results are appended to the live context at full size and re-sent on
# every later iteration of the same run, so a 50kB SQL result is paid for
# again on iterations 2..10. Only the *content* is trimmed: a `role="tool"`
# message cannot be removed, because every provider requires it to follow an
# assistant message carrying the matching `tool_call_id`, and deleting one
# invalidates the whole chain.
#
# The most recent results stay intact because those are the ones being reasoned
# over right now; older ones are already summarised into the model's own
# reasoning and are kept only for reference.
_TOOL_KEEP_FULL = 2
_TOOL_RESULT_CAP_CHARS = 4_000


def _trim_tool_results(context: list[dict]) -> None:
    """Shrink already-consumed tool results in place. Never removes messages."""
    tool_idxs = [i for i, m in enumerate(context) if m.get("role") == "tool"]
    for i in tool_idxs[:-_TOOL_KEEP_FULL]:
        content = context[i].get("content")
        if isinstance(content, str) and len(content) > _TOOL_RESULT_CAP_CHARS:
            context[i]["content"] = (
                content[:_TOOL_RESULT_CAP_CHARS]
                + f"\n[... {len(content) - _TOOL_RESULT_CAP_CHARS} chars trimmed]"
            )


def _context_tokens(context: list[dict]) -> int:
    """Token count of the assembled context, for the router.

    Estimated from the raw strings rather than tokenized properly: this runs on
    every iteration of every run and a real tokenizer pass costs more than the
    decision it feeds is worth. The router only compares against a coarse
    threshold, so a few percent of error does not move the outcome.
    """
    chars = 0
    for msg in context:
        content = msg.get("content") or ""
        if isinstance(content, str):
            chars += len(content)
        for tc in msg.get("tool_calls") or []:
            chars += len(str(tc))
    # ~4 chars per token, matching the estimator in aios.core.tokenizer
    return chars // 4


async def _cached_context_is_fresh(db, conversation_id: str, cached) -> bool:
    """True when no turn except the one being answered landed after the save.

    The old guard compared cache message counts with `get_recent(limit=20)`,
    which is capped and excludes tool rows while the cache includes them. Once
    the cache held ~20 entries it always "won", even if another replica had
    answered newer turns in the meantime, and those turns disappeared from the
    model's context. One row newer is the current user message; two or more
    means somebody else advanced the conversation.
    """
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    since = datetime.fromtimestamp(cached.saved_at or 0.0, tz=timezone.utc)
    newer = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation_id,
                Message.created_at > since,
            )
        )
    ).scalar() or 0
    return newer <= 1


class AgentRuntime:
    """One agent loop per deployed agent.

    All LLM/memory/tool calls route through syscall dispatcher.
    Agent lifecycle managed by scheduler.
    """

    MAX_ITERATIONS = 10

    def __init__(self, agent: AgentModel, db_session_factory=None):
        """`db_session_factory` is accepted and unused.

        It used to be stored on `self._db_factory` and never read, so callers
        that passed one believed the run had a session when it did not — which
        is how runs ended up with no conversation history. Anything that needs a
        session now opens one where it needs it (see `MemoryManager.get_recent`).
        Kept in the signature because a dozen call sites pass it.
        """
        self.agent = agent
        model = agent.llm_config.get("model", "openai/gpt-4o")
        # Resolve provider class only; runtime enforces org/registry policy before LLM calls.
        if model.startswith("ollama/"):
            from aios.core.providers import OllamaProvider

            self.llm = OllamaProvider()
        elif model.startswith("opencode/"):
            from aios.core.providers import OpenRouterProvider

            self.llm = OpenRouterProvider()
        elif model.startswith("openai-direct/"):
            from aios.core.providers import OpenAIProvider

            self.llm = OpenAIProvider()
        elif model.startswith("anthropic-direct/"):
            from aios.core.providers import AnthropicProvider

            self.llm = AnthropicProvider()
        else:
            from aios.core.providers import OpenRouterProvider

            self.llm = OpenRouterProvider()
        actor_ctx = self._actor_context_from_agent(agent)
        self.tool_engine = ToolEngine(
            agent.tools or [],
            org_id=getattr(agent, "org_id", "") or "",
            agent_id=getattr(agent, "id", "") or "",
            **actor_ctx,
        )
        self.memory = MemoryManager(agent.id, llm_provider=self.llm)
        # governance
        gov = agent.governance_config or {}
        self._autonomy = gov.get("autonomy", "draft")
        self._denied_tools = set(gov.get("denied_tools", []) or [])
        self._allowed_tools = gov.get("allowed_tools", "__all__")
        self._max_tokens = gov.get("max_tokens_per_run", 500_000)
        self.MAX_ITERATIONS = gov.get("max_iterations", 10) or 10
        self.MAX_TOOL_CALLS = gov.get("max_tool_calls_per_run", 25) or 25
        # HITL opt-in: per-agent tool list plus the same value/discount ceilings
        # AutonomousAgent already uses. Empty list = only threshold hits block.
        self._hitl_enabled = gov.get("hitl_enabled", True) is not False
        self._hitl_value_threshold = float(gov.get("hitl_value_threshold", 5000) or 0)
        self._hitl_discount_threshold = float(gov.get("hitl_discount_threshold", 10) or 0)
        self._hitl_tools = set(gov.get("hitl_tools") or [])

        # ICM-X stage binding: opt-in via extra_data["icm"]. The manifest's
        # allowlist narrows the agent's tools and its timeout caps the run.
        from aios.icm.agent_binding import assert_paid_workflow_contract, bind_agent_stage

        assert_paid_workflow_contract(agent)
        self.stage = bind_agent_stage(agent)
        self.stage_provenance = None
        self._stage_timeout = None
        if self.stage is not None:
            manifest = self.stage.manifest
            self._denied_tools |= set(manifest.denied_tools)
            if manifest.allowed_tools:
                stage_allowed = set(manifest.allowed_tools)
                self._allowed_tools = (
                    stage_allowed
                    if self._allowed_tools == "__all__"
                    else set(self._allowed_tools) & stage_allowed
                )
            self._stage_timeout = self.stage.timeout_seconds
        from aios.icm.enforcement import BudgetExceeded, StageBudget

        # Per-run deterministic execution budget (declared stage ceilings).
        self._icm_budget = (
            StageBudget.from_manifest(self.stage.manifest, max_tool_calls=self.MAX_TOOL_CALLS)
            if self.stage is not None
            else StageBudget(
                max_llm_calls=self.MAX_ITERATIONS,
                # No stage manifest: use the settings ceiling instead of an
                # unbounded run. Bound stages still use their manifest cap.
                max_cost_usd=settings.unbound_agent_max_cost_usd,
                max_tool_calls=self.MAX_TOOL_CALLS,
            )
        )

    # ─── Syscall wrappers ───

    async def _syscall(self, stype: SyscallType, params: dict,
                       conv_id: str = "", **extra) -> SyscallResponse:
        """Dispatch a syscall with current agent context."""
        req = SyscallRequest(
            type=stype,
            params=params,
            agent_id=self.agent.id,
            conversation_id=conv_id,
        )
        return await syscall_dispatcher.dispatch(req, **extra)

    def _enforce_llm_context_ceiling(self, messages: list[dict], max_tokens: int) -> None:
        max_ctx = None
        if self.stage is not None:
            max_ctx = self.stage.manifest.context.max_context_tokens
        if not max_ctx:
            return
        from aios.core.tokenizer import count_messages_tokens

        used = count_messages_tokens(messages) + int(max_tokens or 0)
        if used > int(max_ctx):
            from aios.icm.enforcement import BudgetExceeded

            raise BudgetExceeded(
                f"ICM context ceiling exceeded: {used} > {int(max_ctx)} tokens"
            )

    async def _llm_chat(self, messages: list[dict], model: str,
                        temperature: float, max_tokens: int,
                        tools: list[dict] | None = None,
                        tool_choice=None) -> dict:
        """Call LLM via syscall or direct fallback."""
        self._enforce_llm_context_ceiling(messages, max_tokens)
        resp = await self._syscall(SyscallType.LLM_CHAT, {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            "tool_choice": tool_choice,
        })
        if resp.ok and resp.data:
            return resp.data
        # direct fallback
        return await self.llm.chat_retry(
            messages=messages, model=model,
            temperature=temperature, max_tokens=max_tokens,
            tools=tools, tool_choice=tool_choice,
        )

    async def _llm_chat_stream(self, messages: list[dict], model: str,
                                temperature: float, max_tokens: int,
                                tools: list[dict] | None = None):
        """Stream LLM via syscall or direct fallback."""
        self._enforce_llm_context_ceiling(messages, max_tokens)
        resp = await self._syscall(SyscallType.LLM_CHAT_STREAM, {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
        })
        if resp.ok and resp.data:
            async for ev in resp.data:
                yield ev
            return
        # direct fallback
        async for ev in self.llm.chat_stream_retry(
            messages=messages, model=model,
            temperature=temperature, max_tokens=max_tokens,
            tools=tools,
        ):
            yield ev

    # ─── Public API ───

    async def run(
        self,
        conversation_id: str,
        user_message: str,
        db: DatabaseBackend | None = None,
        approved_hitl: dict | None = None,
    ) -> str:
        """Non-streaming: collect full response and return."""
        collected = ""
        async for event in self.run_stream(conversation_id, user_message, db, approved_hitl):
            if event["type"] == STREAM_TOKEN:
                collected += event["content"]
            elif event["type"] == STREAM_ERROR:
                logger.error("Agent stream error: %s", event.get("error"))
        return collected or "I'm having trouble completing this request. Please try again."

    async def run_structured(
        self,
        conversation_id: str,
        user_message: str,
        output_schema: dict,
        db: DatabaseBackend | None = None,
    ) -> dict:
        """Run agent with forced structured output matching output_schema."""
        context = await self._build_context(conversation_id, user_message, db)
        output_tool = {
            "type": "function",
            "function": {
                "name": "_output",
                "description": "Respond with structured data matching this schema",
                "parameters": output_schema,
            },
        }
        existing_tools = self.tool_engine.schemas() if self.tool_engine.tools else []
        all_tools = existing_tools + [output_tool]

        # Route on the agent's real tools only. `_output` is the structured
        # output harness, not a capability the model has to reason about
        # choosing — counting it made every structured call look like
        # multi-step tool use and pinned the whole path to the frontier model.
        org_extra = self._org_extra()
        registry_entries = await self._load_runtime_registry(db)
        configured_model = self.agent.llm_config.get("model", "openai/gpt-4o")
        self._assert_model_eligible(configured_model, org_extra, registry_entries)
        ceiling = self.agent.llm_config.get("max_tier") or None
        op_floor = self.agent.llm_config.get("min_tier")
        floor = (
            op_floor
            if op_floor and router.is_routable(op_floor)
            else floor_from_extra(getattr(self.agent, "extra_data", None))
        )
        role = getattr(self.agent, "agent_type", None)
        candidates = [f for f in (floor, router.ROLE_MIN_TIER.get(role) if role else None) if f and router.is_routable(f)]
        if candidates:
            floor = max(candidates, key=router.TIERS.index)
        if (
            ceiling and router.is_routable(ceiling)
            and floor and router.is_routable(floor)
            and router.TIERS.index(floor) > router.TIERS.index(ceiling)
        ):
            floor = ceiling
        decision = route(
            configured_model,
            role=role,
            context_tokens=_context_tokens(context),
            tools=existing_tools,
            autonomy=self._autonomy,
            min_tier=floor,
            org_extra=org_extra,
            registry_entries=registry_entries,
        )
        router.record(decision)
        if decision.changed:
            logger.info(
                "routing structured %s -> %s (%s)",
                self.agent.llm_config.get("model"), decision.model, decision.reason,
            )

        span = start_span("agent_structured", model=decision.model, org_id=self.agent.org_id or "")
        try:
            from aios.core.tracing import estimate_cost

            budget = self._icm_budget
            model = decision.model
            self._assert_model_eligible(model, org_extra, registry_entries)
            input_tokens = max(1, _context_tokens(context))
            output_tokens = max(256, int(input_tokens * 0.05))
            budget.charge(
                estimate_cost(
                    model,
                    input_tokens + output_tokens,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            )
            response = await self._llm_chat(
                messages=context,
                model=model,
                temperature=self.agent.llm_config.get("temperature", 0.5),
                max_tokens=self.agent.llm_config.get("max_tokens", 4096),
                tools=all_tools,
                tool_choice={"type": "function", "function": {"name": "_output"}},
            )
            usage = response.get("usage") or {}
            if usage:
                span.extra["usage"] = usage
                if db is not None:
                    from aios.core.limits import track_usage
                    from aios.core.tracing import estimate_cost_detailed

                    try:
                        await track_usage(
                            self.agent.org_id,
                            db,
                            messages=1,
                            tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                            llm_calls=1,
                            cost_usd=estimate_cost_detailed(
                                decision.model,
                                usage.get("input_tokens", 0),
                                usage.get("output_tokens", 0),
                            ),
                            model=decision.model,
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            provider=decision.model.split("/")[0] if "/" in decision.model else None,
                            cost_kind="internal",
                            attribution={"path": "run_structured", "agent_id": self.agent.id},
                        )
                    except Exception as _e:
                        logger.warning("usage tracking failed for agent %s: %s", self.agent.id, _e)
        except Exception as e:
            logger.exception("Structured run failed for agent %s", self.agent.id)
            end_span(span, error=str(e))
            raise

        retried = False
        while True:
            for tc in (response.get("tool_calls") or []):
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {})
                if isinstance(fn, dict) and fn.get("name") == "_output":
                    try:
                        result = json.loads(fn.get("arguments", "{}"))
                        end_span(span)
                        return result
                    except (TypeError, ValueError):
                        repair = (
                            None if retried else should_escalate(
                                model, malformed_tool_call=True, max_tier=ceiling
                            )
                        )
                        if repair and repair.changed:
                            retried = True
                            router.record(repair)
                            end_span(span)
                            span = start_span(
                                "agent_structured", model=repair.model,
                                org_id=self.agent.org_id or "",
                            )
                            model = repair.model
                            try:
                                self._assert_model_eligible(repair.model, org_extra, registry_entries)
                                budget.charge(
                                    estimate_cost(
                                        repair.model,
                                        input_tokens + output_tokens,
                                        input_tokens=input_tokens,
                                        output_tokens=output_tokens,
                                    )
                                )
                                response = await self._llm_chat(
                                    messages=context,
                                    model=repair.model,
                                    temperature=self.agent.llm_config.get("temperature", 0.5),
                                    max_tokens=self.agent.llm_config.get("max_tokens", 4096),
                                    tools=all_tools,
                                    tool_choice={"type": "function", "function": {"name": "_output"}},
                                )
                                usage = response.get("usage") or {}
                                if usage:
                                    span.extra["usage"] = usage
                                    if db is not None:
                                        from aios.core.limits import track_usage
                                        from aios.core.tracing import estimate_cost_detailed

                                        try:
                                            await track_usage(
                                                self.agent.org_id,
                                                db,
                                                messages=1,
                                                tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                                                llm_calls=1,
                                                cost_usd=estimate_cost_detailed(
                                                    repair.model,
                                                    usage.get("input_tokens", 0),
                                                    usage.get("output_tokens", 0),
                                                ),
                                                model=repair.model,
                                                input_tokens=usage.get("input_tokens", 0),
                                                output_tokens=usage.get("output_tokens", 0),
                                                provider=repair.model.split("/")[0] if "/" in repair.model else None,
                                                cost_kind="internal",
                                                attribution={"path": "run_structured", "agent_id": self.agent.id},
                                            )
                                        except Exception as _e:
                                            logger.warning("repair usage tracking failed for agent %s: %s", self.agent.id, _e)
                            except Exception as e:
                                logger.exception("Structured repair failed for agent %s", self.agent.id)
                                end_span(span, error=str(e))
                                raise
                            break
                        end_span(span)
                        return {"_raw": fn.get("arguments", "")}
            else:
                content = response.get("content", "")
                if content:
                    try:
                        result = json.loads(content)
                    except json.JSONDecodeError:
                        pass
                    else:
                        end_span(span)
                        return result
                end_span(span)
                return {"_raw": content}

    async def run_stream(
        self,
        conversation_id: str,
        user_message: str,
        db: DatabaseBackend | None = None,
        approved_hitl: dict | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Streaming, with every event tagged and published to the canvas.

        Thin wrapper: tagging happens in exactly one place so no yield site can
        ship an anonymous event to subscribers.
        """
        run_id = uuid.uuid4().hex[:12]
        from aios.core.agent_events import emit_stream_event

        collected: list[str] = []
        try:
            if self._stage_timeout:
                # Raising the deadline aborts a runaway stage instead of
                # letting it spend the org's token budget.
                async with asyncio.timeout(self._stage_timeout):
                    async for ev in self._run_stream_inner(conversation_id, user_message, db, approved_hitl):
                        if ev.get("type") == STREAM_TOKEN:
                            collected.append(ev.get("content", ""))
                        yield emit_stream_event(self.agent, ev, run_id)
            else:
                async for ev in self._run_stream_inner(conversation_id, user_message, db, approved_hitl):
                    if ev.get("type") == STREAM_TOKEN:
                        collected.append(ev.get("content", ""))
                    yield emit_stream_event(self.agent, ev, run_id)
        except TimeoutError:
            logger.warning(
                "ICM stage timeout (%ss) for agent %s", self._stage_timeout, self.agent.id
            )
            yield emit_stream_event(
                self.agent,
                {"type": STREAM_ERROR, "error": f"ICM stage timed out after {self._stage_timeout}s"},
                run_id,
            )
        finally:
            if self.stage is not None:
                try:
                    self.stage_provenance = self.stage.post_execute(
                        output="".join(collected), shared={}
                    )
                except Exception:
                    logger.warning(
                        "ICM provenance write failed for agent %s", self.agent.id, exc_info=True
                    )

    async def _run_stream_inner(
        self,
        conversation_id: str,
        user_message: str,
        db: DatabaseBackend | None = None,
        approved_hitl: dict | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Streaming: yield token/tool_call/done events as they happen.

        Includes: health tracking, retry with fallback models, error escalation, telemetry.
        """
        from aios.core.agent_health import health_tracker
        from aios.core.telemetry import telemetry
        import time

        start_time = time.time()
        total_tokens = 0
        total_tool_calls = 0
        # What the provider actually billed. The pre-call budget charge is an
        # estimate; usage reported by the adapter is the attributable number.
        actual_usage = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}
        actual_cost_usd = 0.0

        # check agent health
        if not health_tracker.is_available(self.agent.id):
            yield {"type": STREAM_ERROR, "error": f"Agent {self.agent.name} is stopped due to repeated failures"}
            return

        # P0-15 guardrail: bloqueia LLM se check_org_limits negar (custo/tokens/msgs)
        # Fail CLOSED. An earlier `except Exception: pass` meant a DB blip turned
        # the spend gate off for every run on that process — the one moment the
        # limit matters most is when we cannot afford the run.
        if db is not None:
            from aios.core.limits import check_org_limits as _chk
            try:
                _allowed, _reason = await _chk(self.agent.org_id, db)
            except Exception as _e:
                logger.error("check_org_limits failed for org %s: %s", self.agent.org_id, _e)
                _allowed, _reason = False, "usage check unavailable"
            if not _allowed:
                yield {"type": STREAM_ERROR, "error": _reason}
                return

        # Register the run with the scheduler. `start()` returns None both when
        # the agent was never enqueued (the direct-call path, fine) and when the
        # scheduler is at capacity (not fine) — so ask it to reserve the slot
        # when there is a process to reserve.
        _proc = self.agent.id and scheduler.start(self.agent.id)
        if _proc is None and scheduler.get_process(self.agent.id) is not None:
            yield {
                "type": STREAM_ERROR,
                "error": "scheduler at capacity — agent not started",
            }
            return
        hooks.fire(HookPoint.AGENT_START, HookContext(
            agent_id=self.agent.id,
            org_id=self.agent.org_id,
            conversation_id=conversation_id,
        ))

        try:
            context = await self._build_context(conversation_id, user_message, db)
            from aios.icm.enforcement import BudgetExceeded

            budget = self._icm_budget
            org_extra = self._org_extra()
            registry_entries = await self._load_runtime_registry(db)
            model = self.agent.llm_config.get("model", "openai/gpt-4o")
            self._assert_model_eligible(model, org_extra, registry_entries)
            temp = self.agent.llm_config.get("temperature", 0.7)
            ceiling = self.agent.llm_config.get("max_tier") or None
            # Ratchets up and never down within a run. Without this the
            # escalation was undone on the very next iteration: the router saw
            # "short context, no tools" again and put the run straight back on
            # the cheapest rung, so a struggling run oscillated on the bottom
            # tier and the escalation cost an extra call for nothing.
            # Operator `min_tier` wins when routable; else use learned floor.
            op_floor = self.agent.llm_config.get("min_tier")
            floor = (
                op_floor
                if op_floor and router.is_routable(op_floor)
                else floor_from_extra(getattr(self.agent, "extra_data", None))
            )
            role = getattr(self.agent, "agent_type", None)
            candidates = [f for f in (floor, router.ROLE_MIN_TIER.get(role) if role else None) if f and router.is_routable(f)]
            if candidates:
                floor = max(candidates, key=router.TIERS.index)
            if (
                ceiling and router.is_routable(ceiling)
                and floor and router.is_routable(floor)
                and router.TIERS.index(floor) > router.TIERS.index(ceiling)
            ):
                floor = ceiling

            for iteration in range(self.MAX_ITERATIONS):
                tools = self.tool_engine.schemas() if self.tool_engine.tools else None

                # Route per iteration, not once per run: whether tools are
                # attached is only known here, and it is the signal that decides
                # whether this is a lookup or multi-step reasoning.
                decision = route(
                    model,
                    role=role,
                    context_tokens=_context_tokens(context),
                    tools=tools,
                    autonomy=self._autonomy,
                    max_tokens=self.agent.llm_config.get("max_tokens", 4096),
                    min_tier=floor,
                    org_extra=org_extra,
                    registry_entries=registry_entries,
                )
                router.record(decision)
                if decision.changed:
                    logger.info(
                        "routing %s -> %s (%s)", model, decision.model, decision.reason
                    )
                    model = decision.model
                self._assert_model_eligible(model, org_extra, registry_entries)

                # check cache for first iteration (no tool calls)
                if iteration == 0 and not tools:
                    cached = cache.get(context, model, temp, tools, self.agent.org_id)
                    if cached:
                        content = cached.get("content", "")
                        if content:
                            yield {"type": STREAM_TOKEN, "content": content}
                        if cached.get("tool_calls"):
                            yield {"type": STREAM_TOOL_CALL, "tool_calls": cached["tool_calls"]}
                        yield {"type": STREAM_DONE}
                        return

                response_content = ""
                response_tool_calls = None

                try:
                    from aios.core.tracing import estimate_cost

                    input_tokens = max(1, _context_tokens(context))
                    output_tokens = max(256, int(input_tokens * 0.05))
                    budget.charge(
                        estimate_cost(
                            model,
                            input_tokens + output_tokens,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        )
                    )
                except BudgetExceeded as exc:
                    yield {"type": STREAM_ERROR, "error": f"ICM stage budget exceeded: {exc}"}
                    return

                async for event in self._llm_chat_stream(
                    messages=context,
                    model=model,
                    temperature=temp,
                    max_tokens=self.agent.llm_config.get("max_tokens", 4096),
                    tools=tools,
                ):
                    if event["type"] == STREAM_TOKEN:
                        response_content += event["content"]
                        yield event
                    elif event["type"] == STREAM_TOOL_CALL:
                        response_tool_calls = event["tool_calls"]
                        total_tool_calls += len(response_tool_calls or [])
                        # Token accounting. This counter was declared and never
                        # incremented, so every telemetry.record(tokens=...) and
                        # every cost dashboard read 0. Providers do not surface
                        # usage on the stream, so count what we actually emitted.
                        from aios.core.tokenizer import count_tokens as _ct

                        total_tokens += _ct(response_content or "")
                        # Re-yield: subscribers (agent canvas node activity, and
                        # the dashboard sandbox tool counter) already handle
                        # this event, but it was swallowed here so neither ever
                        # saw a tool call.
                        yield event
                    elif event["type"] == STREAM_DONE:
                        u = event.get("usage") or {}
                        if u.get("input_tokens") or u.get("output_tokens"):
                            actual_usage["input_tokens"] += u.get("input_tokens", 0)
                            actual_usage["output_tokens"] += u.get("output_tokens", 0)
                            actual_usage["cached_tokens"] += u.get("cached_tokens", 0)
                            from aios.core.tracing import estimate_cost_detailed

                            actual_cost_usd += estimate_cost_detailed(
                                model, u.get("input_tokens", 0), u.get("output_tokens", 0)
                            )
                    elif event["type"] == STREAM_ERROR:
                        yield event
                        return

                if response_tool_calls:
                    context.append({
                        "role": "assistant",
                        "content": response_content,
                        "tool_calls": response_tool_calls,
                    })
                    scheduler.block(self.agent.id)  # waiting on tool
                    for tc in response_tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments", "{}")
                        hitl_reason = self._hitl_tool_reason(fn_name, fn_args)
                        approved_match = False
                        if isinstance(approved_hitl, dict):
                            try:
                                parsed_args = json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                            except (TypeError, ValueError):
                                parsed_args = None
                            if (
                                approved_hitl.get("tool_name") == fn_name
                                and isinstance(parsed_args, dict)
                                and parsed_args == approved_hitl.get("tool_args")
                            ):
                                approved_match = True
                                approved_hitl = None  # marker covers one call only

                        # governance check — deny tool if blocked
                        if fn_name in self._denied_tools:
                            result = f"Tool '{fn_name}' is not allowed by governance policy."
                            logger.warning("Governance blocked tool '%s' for agent %s", fn_name, self.agent.id)
                        elif self._allowed_tools != "__all__" and fn_name not in self._allowed_tools:
                            result = f"Tool '{fn_name}' is not in the allowed list."
                            logger.warning("Governance blocked tool '%s' (not in allow-list) for agent %s", fn_name, self.agent.id)
                        elif self._autonomy in ("ask", "ask_tools", "ask_all") or hitl_reason or approved_match:
                            # approval mode — block before the side effect runs
                            if approved_match:
                                approved = True
                            else:
                                from aios.core.approval import approval_manager
                                action_id = str(uuid.uuid4())
                                hooks.fire(HookPoint.APPROVAL_REQUESTED, HookContext(
                                    agent_id=self.agent.id,
                                    conversation_id=conversation_id,
                                    data={"action_id": action_id, "tool_name": fn_name},
                                ))
                                approval_args = json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                                actor_user_id = str(self._actor_context_from_agent(self.agent).get("actor_user_id") or "")
                                if actor_user_id and isinstance(approval_args, dict):
                                    approval_args = {**approval_args, "_requested_by": actor_user_id}
                                approved = await approval_manager.request_approval(
                                    action_id=action_id,
                                    agent_id=self.agent.id,
                                    conversation_id=conversation_id,
                                    tool_name=fn_name,
                                    tool_args=approval_args,
                                    context_summary=f"HITL: {hitl_reason}" if hitl_reason else response_content[:200],
                                    # Without this the row lands with org_id="" and
                                    # the approvals API filters it out for every
                                    # tenant, so nobody could ever approve it — the
                                    # agent waited the full timeout on an action no
                                    # human could see.
                                    org_id=self.agent.org_id,
                                )
                            if not approved:
                                result = f"Tool '{fn_name}' was not approved by human."
                                logger.info("Approval denied for tool '%s' on agent %s", fn_name, self.agent.id)
                            else:
                                try:
                                    self._icm_enforce_tool(fn_name, conversation_id)
                                    self._icm_budget.charge_tool()
                                except PermissionError as exc:
                                    result = f"ICM approval required: {exc}"
                                except BudgetExceeded as exc:
                                    yield {"type": STREAM_ERROR, "error": f"ICM stage budget exceeded: {exc}"}
                                    return
                                else:
                                    cached_result = tool_cache.get(fn_name, fn_args, self.agent.org_id)
                                    if cached_result is not None:
                                        result = cached_result
                                    else:
                                        try:
                                            result = await self.tool_engine.execute(fn_name, fn_args, approved=True)
                                            tool_cache.set(fn_name, fn_args, result, self.agent.org_id)
                                        except Exception as e:
                                            logger.exception("Tool execution failed: %s", fn_name)
                                            result = f"Tool error: {e}"
                        else:
                            try:
                                self._icm_enforce_tool(fn_name, conversation_id)
                                self._icm_budget.charge_tool()
                            except PermissionError as exc:
                                result = f"ICM approval required: {exc}"
                            except BudgetExceeded as exc:
                                yield {"type": STREAM_ERROR, "error": f"ICM stage budget exceeded: {exc}"}
                                return
                            else:
                                cached_result = tool_cache.get(fn_name, fn_args, self.agent.org_id)
                                if cached_result is not None:
                                    result = cached_result
                                else:
                                    try:
                                        result = await self.tool_engine.execute(fn_name, fn_args)
                                        tool_cache.set(fn_name, fn_args, result, self.agent.org_id)
                                    except Exception as e:
                                        logger.exception("Tool execution failed: %s", fn_name)
                                        result = f"Tool error: {e}"
                        context.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": result,
                        })
                        if db:
                            db.add(Message(
                                conversation_id=conversation_id,
                                org_id=self.agent.org_id,
                                role="tool",
                                content=str(result)[:2000],
                                agent_id=self.agent.id,
                                tool_results={"id": tc["id"], "name": fn.get("name")},
                            ))
                        # skill extraction — fire-and-forget after successful tool call
                        if result and "Tool error" not in str(result):
                            try:
                                from aios.core.skills import skill_store

                                async def _extract():
                                    # One row per tool: without this every call
                                    # appended another identical auto:{tool} row,
                                    # so the skill index filled with duplicates
                                    # that all scored the same and crowded out
                                    # real skills.
                                    if await skill_store.exists(
                                        agent_id=self.agent.id,
                                        org_id=self.agent.org_id,
                                        name=f"auto:{fn_name}",
                                    ):
                                        return
                                    await skill_store.create(
                                        agent_id=self.agent.id,
                                        org_id=self.agent.org_id,
                                        name=f"auto:{fn_name}",
                                        description=f"Auto-extracted from tool call {fn_name}",
                                        skill_type="tool_pattern",
                                        content=f"Tool: {fn_name}\nArgs: {fn_args}\nResult: {str(result)[:500]}",
                                        source_conversation_id=conversation_id,
                                    )

                                asyncio.create_task(_extract())
                            except Exception:
                                pass  # skill extraction is best-effort
                    scheduler.unblock(self.agent.id)
                    _trim_tool_results(context)
                    yield {"type": STREAM_TOKEN, "content": "\n"}
                    continue

                # No tool calls — final response
                if response_content:
                    from aios.core.tokenizer import count_tokens as _ct

                    total_tokens += _ct(response_content)
                    await self.memory.add(conversation_id, "assistant", response_content)
                    cache.set(context, model, temp, {"content": response_content, "tool_calls": None}, tools, self.agent.org_id)
                    if db:
                        db.add(Message(
                            conversation_id=conversation_id,
                            org_id=self.agent.org_id,
                            role="assistant",
                            content=response_content,
                            agent_id=self.agent.id,
                        ))
                        await db.commit()
                    # save context state
                    context_manager.save(conversation_id, self.agent.id, context)
                else:
                    # No tool calls and no text. The model returned nothing —
                    # a cheap model that has given up looks exactly like this.
                    # Repair it instead of shipping an empty turn.
                    repair = should_escalate(
                        model, empty_response=True, max_tier=ceiling
                    )
                    if repair:
                        router.record(repair)
                    if repair and repair.changed:
                        logger.warning(
                            "empty response on %s, escalating to %s", model, repair.model
                        )
                        model = repair.model
                        floor = repair.model
                        continue

                yield {"type": STREAM_DONE}
                health_tracker.record_success(self.agent.id)
                response_ms = int((time.time() - start_time) * 1000)
                billed_tokens = (
                    actual_usage["input_tokens"] + actual_usage["output_tokens"]
                    if actual_usage["input_tokens"] or actual_usage["output_tokens"]
                    else total_tokens
                )
                telemetry.record(self.agent.id, self.agent.org_id, response_ms=response_ms, tokens=billed_tokens, tool_calls=total_tool_calls)
                if db is not None:
                    from aios.core.limits import track_usage

                    try:
                        await track_usage(
                            self.agent.org_id,
                            db,
                            messages=1,
                            tokens=billed_tokens,
                            llm_calls=1,
                            cost_usd=actual_cost_usd or self._icm_budget.cost_usd,
                            model=model,
                            input_tokens=actual_usage["input_tokens"],
                            output_tokens=actual_usage["output_tokens"],
                            provider=model.split("/")[0] if "/" in str(model) else None,
                            cost_kind="internal",
                            attribution={"path": "run_stream", "agent_id": self.agent.id},
                        )
                    except Exception as _e:
                        logger.warning("usage tracking failed for agent %s: %s", self.agent.id, _e)
                return

            logger.warning("Agent %s hit max iterations (%d)", self.agent.id, self.MAX_ITERATIONS)
            # Exhausting the budget is a signal, not a verdict: a cheap model
            # that cannot hold a multi-step thread looks identical to an agent
            # that legitimately needs more rounds. Record it so the next run on
            # this agent starts on a stronger tier instead of discovering it
            # again.
            # Remember the promotion for next time. Without this the floor was
            # in-memory only, so every worker process and every restart
            # rediscovered the same failure — a cheap call, an escalation and a
            # wasted answer, repeated forever.
            #
            # `changed=False` here is correct and common, not a bug: an agent
            # already configured on the strongest tier that runs out of budget
            # has nowhere to be promoted to, and there is nothing to learn.
            repair = should_escalate(model, hit_iteration_limit=True, max_tier=ceiling)
            if repair:
                router.record(repair)
            if repair and repair.changed:
                await self._pin_tier(repair.model, f"escalated: {repair.reason}", db=db)
            yield {"type": STREAM_TOKEN, "content": "I'm having trouble completing this request. Please try again."}
            yield {"type": STREAM_DONE}
            # NOT record_failure: exhausting the iteration budget is not a broken
            # agent. An agent that legitimately needs 11 tool round-trips was
            # scored as failing, and 15 of those drive it to `stopped` — where
            # record_success will not recover it and only a manual reset does.
            # The customer sees a permanently dead agent.
            response_ms = int((time.time() - start_time) * 1000)
            telemetry.record(self.agent.id, self.agent.org_id, response_ms=response_ms, tokens=actual_usage["input_tokens"] + actual_usage["output_tokens"])
            if db is not None:
                from aios.core.limits import track_usage

                try:
                    await track_usage(
                        self.agent.org_id,
                        db,
                        messages=1,
                        tokens=actual_usage["input_tokens"] + actual_usage["output_tokens"],
                        llm_calls=1,
                        cost_usd=actual_cost_usd or self._icm_budget.cost_usd,
                        model=model,
                        input_tokens=actual_usage["input_tokens"],
                        output_tokens=actual_usage["output_tokens"],
                        provider=model.split("/")[0] if "/" in str(model) else None,
                        cost_kind="internal",
                        attribution={"path": "run_stream_exhausted", "agent_id": self.agent.id},
                    )
                except Exception as _e:
                    logger.warning("usage tracking failed for agent %s: %s", self.agent.id, _e)
        except Exception as e:
            logger.exception("Agent stream failed: agent=%s conv=%s", self.agent.id, conversation_id)
            health_tracker.record_failure(self.agent.id, str(e)[:200])
            response_ms = int((time.time() - start_time) * 1000)
            telemetry.record(self.agent.id, self.agent.org_id, response_ms=response_ms, error=True)
            hooks.fire(HookPoint.AGENT_ERROR, HookContext(
                agent_id=self.agent.id,
                org_id=self.agent.org_id,
                conversation_id=conversation_id,
                data={"error": str(e)},
            ))
            yield {"type": STREAM_ERROR, "error": "Agent encountered an error. Please try again."}
        finally:
            scheduler.terminate(self.agent.id)
            hooks.fire(HookPoint.AGENT_END, HookContext(
                agent_id=self.agent.id,
                org_id=self.agent.org_id,
                conversation_id=conversation_id,
            ))

    async def build_context(
        self, conversation_id: str, user_message: str, db: DatabaseBackend | None = None
    ) -> list[dict]:
        return await self._build_context(conversation_id, user_message, db)

    def _icm_execution_shared(self, conversation_id: str = "") -> dict:
        run_key = conversation_id or f"agent-{self.agent.id}"
        cache = getattr(self, "_icm_execution_shared_cache", None)
        if cache is None:
            cache = {}
            self._icm_execution_shared_cache = cache
        shared = cache.get(run_key)
        if shared is None:
            shared = {
                "run_id": run_key,
                "task_id": run_key,
                "conversation_id": conversation_id,
            }
            cache[run_key] = shared
        shared.pop("icm_approval", None)
        shared.pop("icm_preapproved", None)
        extra = getattr(self.agent, "extra_data", None) or {}
        cfg = extra.get("icm") if isinstance(extra.get("icm"), dict) else {}
        gov = getattr(self.agent, "governance_config", None) or {}
        for src in (
            cfg.get("approval"),
            extra.get("icm_approval"),
            gov.get("icm_approval"),
        ):
            if isinstance(src, dict):
                shared["icm_approval"] = src
                break
        for src in (
            cfg.get("preapproved"),
            extra.get("icm_preapproved"),
            gov.get("icm_preapproved"),
        ):
            if isinstance(src, dict) and src.get("approved") is True:
                shared["icm_preapproved"] = src
                break
        return shared

    def _hitl_tool_reason(self, fn_name: str, fn_args) -> str:
        """Why this tool call needs a human, empty when it does not.

        Central action policy authoritative for risky/unknown/fail-closed classes.
        Agent HITL config can tighten (explicit tool list) but not silently bypass high-risk.
        """
        if fn_name in self._hitl_tools:
            return f"tool '{fn_name}' requires approval by agent policy"

        decision = classify_tool_action(
            fn_name, fn_args,
            context={
                "hitl_value_threshold": self._hitl_value_threshold,
                "hitl_discount_threshold": self._hitl_discount_threshold,
            },
        )
        if decision.requires_approval:
            # If operator disabled HITL globally, preserve legacy behavior only for
            # non-fail-closed, non-destructive classes; still block fail-closed/unknown.
            if not self._hitl_enabled and not decision.fail_closed and decision.action_class.value not in {
                "destructive", "prod_publish", "unknown_side_effect", "pii_legal",
            }:
                return ""
            return decision.reason or f"{decision.action_class.value} requires approval"
        return ""

    def _icm_enforce_tool(self, fn_name: str, conversation_id: str = "") -> None:
        stage = self.stage
        if stage is None or not stage.requires_approval:
            return
        shared = self._icm_execution_shared(conversation_id)
        stage.enforce_execution(shared, action=fn_name)

    async def _spawn_subagent(self, task_prompt: str, timeout: float = 120.0) -> str:
        """Spawn an isolated subprocess agent. Returns result output."""
        from aios.core.subagent import SubagentSpawnError, subagent_pool
        try:
            result = await subagent_pool.spawn(
                agent_config={
                    "id": self.agent.id,
                    "name": self.agent.name,
                    "llm_config": self.agent.llm_config,
                    "system_prompt": self.agent.system_prompt,
                    "tools": self.agent.tools or [],
                    "governance_config": self.agent.governance_config or {},
                    "org_id": self.agent.org_id,
                },
                task_prompt=task_prompt,
                timeout=timeout,
            )
        except SubagentSpawnError as exc:
            return f"Subagent denied: {exc}"
        except Exception as exc:
            logger.warning("subagent spawn failed for agent %s: %s", self.agent.id, exc)
            return f"Subagent failed: {exc}"
        return result.output or f"Subagent {result.status}: {result.error}"

    async def load_project_skills(self, project_path: str) -> str:
        """Load and format project skills for explicit injection."""
        from aios.core.skill_loader import skill_loader
        skills = skill_loader.load_skills(project_path)
        return skill_loader.format_skills_for_context(skills)

    @staticmethod
    def _actor_context_from_agent(agent: AgentModel) -> dict[str, Any]:
        """Best-effort actor hints from agent config.

        Fail-closed remains default: only explicit hints are injected. Runtime
        cannot safely resolve arbitrary user grants in sync init.
        """
        extra = getattr(agent, "extra_data", None) or {}
        gov = getattr(agent, "governance_config", None) or {}
        candidates: list[dict] = []
        for src in (
            extra.get("actor_context"),
            extra.get("icm_actor"),
            gov.get("actor_context"),
            gov.get("icm_actor"),
        ):
            if isinstance(src, dict):
                candidates.append(src)
        icm = extra.get("icm")
        if isinstance(icm, dict):
            for k in ("actor_context", "actor"):
                src = icm.get(k)
                if isinstance(src, dict):
                    candidates.append(src)

        actor_user_id = ""
        actor_departments: set[str] = set()
        granted_record_ids: set[str] = set()
        is_founder = False
        found = False
        for src in candidates:
            found = True
            actor_user_id = actor_user_id or str(src.get("actor_user_id") or src.get("user_id") or "")
            actor_departments |= {str(d) for d in (src.get("actor_departments") or src.get("departments") or []) if d}
            granted_record_ids |= {str(r) for r in (src.get("granted_record_ids") or src.get("granted_records") or []) if r}
            is_founder = is_founder or bool(src.get("is_founder", False))
        if not found:
            return {}
        return {
            "actor_user_id": actor_user_id,
            "actor_departments": actor_departments,
            "is_founder": is_founder,
            "granted_record_ids": granted_record_ids,
        }

    def _org_extra(self) -> dict | None:
        extra = getattr(self.agent, "extra_data", None)
        return extra if isinstance(extra, dict) else None

    async def _load_runtime_registry(self, db) -> list | None:
        """Load org-visible registry entries; cache per runtime for deterministic fallback.

        Async-safe: awaits DB load when possible. On load failure, returns cached
        entries if present. Missing entries fail closed only when registry approval
        is explicitly required by org policy.
        """
        cache_attr = "_runtime_registry_entries"
        if hasattr(self, cache_attr):
            return getattr(self, cache_attr)
        try:
            from sqlalchemy import or_, select
            from aios.governance.model_intelligence import ModelRegistryEntry

            org_id = getattr(self.agent, "org_id", None)
            q = select(ModelRegistryEntry)
            if org_id:
                q = q.where(or_(ModelRegistryEntry.org_id == org_id, ModelRegistryEntry.org_id.is_(None)))

            if db is not None:
                rows = (await db.execute(q)).scalars().all()
            else:
                from aios.db.backend import db_session

                async with db_session() as session:
                    rows = (await session.execute(q)).scalars().all()
            entries = list(rows)
            setattr(self, cache_attr, entries)
            return entries
        except Exception:
            logger.debug("registry load failed for agent %s", self.agent.id, exc_info=True)
            policy = (self._org_extra() or {}).get("model_policy") or {}
            if policy.get("require_registry_approval"):
                # Fail closed: mark as loaded-but-unavailable empty set.
                setattr(self, cache_attr, [])
                return []
            # No enforcement: allow configured path with warning metadata via None sentinel? 
            # Keep unavailable as empty cache marker absent; return None so router applies compat fallback.
            return None

    def _assert_model_eligible(self, model: str, org_extra: dict | None, registry_entries: list | None) -> None:
        ok, reason, meta = model_runtime_eligible(
            model, org_extra=org_extra, registry_entries=registry_entries
        )
        if not ok:
            from aios.core.providers import LLMError

            raise LLMError(f"Model policy blocked: {reason} {meta}".strip())

    async def _pin_tier(self, model: str, why: str, db=None) -> None:
        """Remember a model escalation so the next run starts on a stronger tier.

        Written to `extra_data`, never to `llm_config`: the operator's
        configured model stays exactly as they set it, and the promotion is a
        separate, inspectable, expiring record.

        This was in-memory only, which meant every worker process and every
        restart rediscovered the same failure from scratch — paying a cheap
        call, an escalation and a wasted answer each time, forever.
        """
        from aios.core.router import remember_floor

        current = getattr(self.agent, "extra_data", None) or {}
        updated = remember_floor(current, model, why)
        if updated == current:
            return
        self.agent.extra_data = updated
        logger.info(
            "agent %s learned floor %s (%s)", self.agent.id, model, why
        )
        if db is None:
            # Direct-call paths run without a session (see the `db` parameter).
            # The floor still applies to this process; it just does not outlive
            # it, which is the old behaviour rather than a regression.
            return
        try:
            db.add(self.agent)
            await db.commit()
        except Exception:
            logger.warning(
                "could not persist routing floor for agent %s", self.agent.id,
                exc_info=True,
            )

    async def _build_context(
        self, conversation_id: str, user_message: str, db: DatabaseBackend | None = None
    ) -> list[dict]:
        model = self.agent.llm_config.get("model", "openai/gpt-4o")
        ctx_window = _ctx_window(model)
        max_output = self.agent.llm_config.get("max_tokens", 4096)
        ctx = [{"role": "system", "content": self.agent.system_prompt}]

        # Frozen curated snapshot (MEMORY.md / USER.md semantics): read once at
        # run start, never refreshed mid-run, so writes made by the memory tool
        # during this run take effect from the next one. Bounded by the block
        # capacities (~1.3k tokens worst case), and load_curated never raises.
        try:
            from aios.core import curated as _curated

            _blocks = await _curated.load_blocks(
                getattr(self.agent, "id", "") or "",
                getattr(self.agent, "org_id", "") or "",
            )
            _mem = _curated.format_block("memory", _blocks["memory"])
            _usr = _curated.format_block("user", _blocks["user"])
            if _mem or _usr:
                ctx.append({"role": "system", "content": "\n\n".join(b for b in (_mem, _usr) if b)})
        except Exception:
            logger.debug("curated snapshot failed", exc_info=True)

        recent = await self.memory.get_recent(conversation_id, limit=20, db=db)
        ctx.extend(recent)

        # Prefer the in-process context cache when nothing newer has landed in
        # the DB since it was saved. The DB replay carries user/assistant text
        # only — tool rows are filtered out (a bare `role="tool"` with no
        # tool_call_id is rejected by every provider), so the assistant's
        # tool_calls chain is lost across turns. The cache holds the assembled
        # block with that chain intact, and `context_manager.save()` at the end
        # of a run already writes it — but nothing ever read it back, so the
        # save was dead weight. Freshness is checked against DB timestamps, not
        # message counts: the counts are not comparable (cache includes tool
        # rows, `recent` is capped at 20).
        cached = context_manager.load(conversation_id, self.agent.id)
        if (
            cached
            and cached.message_count >= len(recent)
            and db is not None
            and await _cached_context_is_fresh(db, conversation_id, cached)
        ):
            ctx = [ctx[0]] + list(cached.message_block)

        # Feed the long-term extractor. Nothing else passes a "user" turn to it.
        try:
            await self.memory.note_user_turn(conversation_id, user_message)
        except Exception:
            logger.debug("long-term memory extraction failed", exc_info=True)

        # memory pipeline: inject relevant past context
        injections = await self.memory.get_context_injections(user_message, top_k=3)
        ctx.extend(injections)
        # second brain: AgentDB reflections + learnings (best-effort)
        try:
            from aios.core.second_brain import get_second_brain_injections
            ctx.extend(await get_second_brain_injections(
                self.agent.id, self.agent.org_id or "", user_message, top_k=3
            ))
        except Exception:
            logger.debug("second_brain injection failed", exc_info=True)

        # skill injection — load relevant skills for this task
        try:
            from aios.core.skills import skill_store
            from aios.core.skill_loader import skill_loader

            # Load DB-stored skills (extracted from past runs)
            db_skills = await skill_store.list(agent_id=self.agent.id, q=user_message[:100])

            # Load project skills (AGENTS.md, CLAUDE.md, etc.) — runtime injection
            # Check if agent has a project path configured
            project_path = (self.agent.extra_data or {}).get("project_path") if hasattr(self.agent, 'extra_data') else None
            project_skills = skill_loader.get_skills_for_task(user_message, project_path, max_skills=5)

            all_skill_lines = []
            if db_skills:
                all_skill_lines.extend([f"- {s.name}: {s.description}" for s in db_skills[:3]])
            if project_skills:
                all_skill_lines.extend([f"- {s.name} (project): {s.description}" for s in project_skills[:3]])

            if all_skill_lines:
                ctx.append({"role": "system", "content": "Relevant skills:\n" + "\n".join(all_skill_lines)})
        except Exception:
            pass  # skill injection is best-effort

        ctx.append({"role": "user", "content": user_message})

        # compress oldest messages to fit token budget
        ctx = await context_manager.compress_and_fit(
            ctx, max_tokens=ctx_window, reserve_tokens=max_output,
            llm_provider=self.llm,
        )

        return ctx
