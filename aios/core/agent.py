"""Agent runtime — think → act → observe → respond loop.

Uses syscall layer for all kernel interactions (LLM, memory, tools).
Agent scheduler manages queue and lifecycle.
"""

import asyncio
import json
import logging
import uuid

from typing import AsyncGenerator
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
from aios.core.router import floor_from_extra, route, should_escalate
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
        self.llm = get_provider(model)
        self.tool_engine = ToolEngine(
            agent.tools or [],
            org_id=getattr(agent, "org_id", "") or "",
            agent_id=getattr(agent, "id", "") or "",
        )
        self.memory = MemoryManager(agent.id, llm_provider=self.llm)
        # governance
        gov = agent.governance_config or {}
        self._autonomy = gov.get("autonomy", "draft")
        self._denied_tools = set(gov.get("denied_tools", []) or [])
        self._allowed_tools = gov.get("allowed_tools", "__all__")
        self._max_tokens = gov.get("max_tokens_per_run", 500_000)
        self.MAX_ITERATIONS = gov.get("max_iterations", 10) or 10

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

    async def _llm_chat(self, messages: list[dict], model: str,
                        temperature: float, max_tokens: int,
                        tools: list[dict] | None = None,
                        tool_choice=None) -> dict:
        """Call LLM via syscall or direct fallback."""
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
    ) -> str:
        """Non-streaming: collect full response and return."""
        collected = ""
        async for event in self.run_stream(conversation_id, user_message, db):
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
        decision = route(
            self.agent.llm_config.get("model", "openai/gpt-4o"),
            context_tokens=_context_tokens(context),
            tools=existing_tools,
            autonomy=self._autonomy,
            min_tier=self.agent.llm_config.get("min_tier") or None,
        )
        router.record(decision)
        if decision.changed:
            logger.info(
                "routing structured %s -> %s (%s)",
                self.agent.llm_config.get("model"), decision.model, decision.reason,
            )

        span = start_span("agent_structured", model=decision.model)
        try:
            response = await self._llm_chat(
                messages=context,
                model=decision.model,
                temperature=self.agent.llm_config.get("temperature", 0.5),
                max_tokens=self.agent.llm_config.get("max_tokens", 4096),
                tools=all_tools,
                tool_choice={"type": "function", "function": {"name": "_output"}},
            )
        except Exception as e:
            logger.exception("Structured run failed for agent %s", self.agent.id)
            end_span(span, error=str(e))
            raise

        for tc in (response.get("tool_calls") or []):
            fn = tc.get("function", {})
            if fn.get("name") == "_output":
                try:
                    result = json.loads(fn.get("arguments", "{}"))
                    end_span(span)
                    return result
                except json.JSONDecodeError:
                    end_span(span)
                    return {"_raw": fn.get("arguments", "")}
        content = response.get("content", "")
        if content:
            try:
                end_span(span)
                return json.loads(content)
            except json.JSONDecodeError:
                pass
        end_span(span)
        return {"_raw": content}

    async def run_stream(
        self,
        conversation_id: str,
        user_message: str,
        db: DatabaseBackend | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Streaming, with every event tagged and published to the canvas.

        Thin wrapper: tagging happens in exactly one place so no yield site can
        ship an anonymous event to subscribers.
        """
        run_id = uuid.uuid4().hex[:12]
        from aios.core.agent_events import emit_stream_event

        async for ev in self._run_stream_inner(conversation_id, user_message, db):
            yield emit_stream_event(self.agent, ev, run_id)

    async def _run_stream_inner(
        self,
        conversation_id: str,
        user_message: str,
        db: DatabaseBackend | None = None,
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
            model = self.agent.llm_config.get("model", "openai/gpt-4o")
            temp = self.agent.llm_config.get("temperature", 0.7)
            ceiling = self.agent.llm_config.get("max_tier") or None
            # Ratchets up and never down within a run. Without this the
            # escalation was undone on the very next iteration: the router saw
            # "short context, no tools" again and put the run straight back on
            # the cheapest rung, so a struggling run oscillated on the bottom
            # tier and the escalation cost an extra call for nothing.
            # The operator's `min_tier` wins when set; otherwise fall back to
            # whatever this agent previously learned (and still has grounds for).
            floor = self.agent.llm_config.get("min_tier") or floor_from_extra(
                getattr(self.agent, "extra_data", None)
            )

            for iteration in range(self.MAX_ITERATIONS):
                tools = self.tool_engine.schemas() if self.tool_engine.tools else None

                # Route per iteration, not once per run: whether tools are
                # attached is only known here, and it is the signal that decides
                # whether this is a lookup or multi-step reasoning.
                decision = route(
                    model,
                    context_tokens=_context_tokens(context),
                    tools=tools,
                    autonomy=self._autonomy,
                    max_tokens=self.agent.llm_config.get("max_tokens", 4096),
                    min_tier=floor,
                )
                router.record(decision)
                if decision.changed:
                    logger.info(
                        "routing %s -> %s (%s)", model, decision.model, decision.reason
                    )
                    model = decision.model

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

                        # governance check — deny tool if blocked
                        if fn_name in self._denied_tools:
                            result = f"Tool '{fn_name}' is not allowed by governance policy."
                            logger.warning("Governance blocked tool '%s' for agent %s", fn_name, self.agent.id)
                        elif self._allowed_tools != "__all__" and fn_name not in self._allowed_tools:
                            result = f"Tool '{fn_name}' is not in the allowed list."
                            logger.warning("Governance blocked tool '%s' (not in allow-list) for agent %s", fn_name, self.agent.id)
                        elif self._autonomy in ("ask", "ask_tools", "ask_all"):
                            # approval mode — block until human decides
                            from aios.core.approval import approval_manager
                            action_id = str(uuid.uuid4())
                            hooks.fire(HookPoint.APPROVAL_REQUESTED, HookContext(
                                agent_id=self.agent.id,
                                conversation_id=conversation_id,
                                data={"action_id": action_id, "tool_name": fn_name},
                            ))
                            approved = await approval_manager.request_approval(
                                action_id=action_id,
                                agent_id=self.agent.id,
                                conversation_id=conversation_id,
                                tool_name=fn_name,
                                tool_args=json.loads(fn_args) if isinstance(fn_args, str) else fn_args,
                                context_summary=response_content[:200],
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
                telemetry.record(self.agent.id, self.agent.org_id, response_ms=response_ms, tokens=total_tokens, tool_calls=total_tool_calls)
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
            telemetry.record(self.agent.id, self.agent.org_id, response_ms=response_ms)
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

    async def _spawn_subagent(self, task_prompt: str, timeout: float = 120.0) -> str:
        """Spawn an isolated subprocess agent. Returns result output."""
        from aios.core.subagent import subagent_pool
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
        return result.output or f"Subagent {result.status}: {result.error}"

    async def load_project_skills(self, project_path: str) -> str:
        """Load and format project skills for explicit injection."""
        from aios.core.skill_loader import skill_loader
        skills = skill_loader.load_skills(project_path)
        return skill_loader.format_skills_for_context(skills)

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

        # Prefer the in-process context cache when it is at least as complete as
        # what the DB gave us. The DB replay carries user/assistant text only —
        # tool rows are filtered out (a bare `role="tool"` with no tool_call_id
        # is rejected by every provider), so the assistant's tool_calls chain is
        # lost across turns. The cache holds the assembled block with that chain
        # intact, and `context_manager.save()` at the end of a run already writes
        # it — but nothing ever read it back, so the save was dead weight.
        # Guarded by length: if another process wrote newer turns, the DB copy
        # wins and nothing is lost.
        cached = context_manager.load(conversation_id, self.agent.id)
        if cached and cached.message_count >= len(recent):
            ctx = [ctx[0]] + list(cached.message_block)

        # Feed the long-term extractor. Nothing else passes a "user" turn to it.
        try:
            await self.memory.note_user_turn(conversation_id, user_message)
        except Exception:
            logger.debug("long-term memory extraction failed", exc_info=True)

        # memory pipeline: inject relevant past context
        injections = await self.memory.get_context_injections(user_message, top_k=3)
        ctx.extend(injections)

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
