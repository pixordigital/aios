"""Agent runtime — think → act → observe → respond loop.

Uses syscall layer for all kernel interactions (LLM, memory, tools).
Agent scheduler manages queue and lifecycle.
"""

import json
import logging
import time

from typing import AsyncGenerator
from aios.db.backend import DatabaseBackend

from aios.core.cache import cache, tool_cache
from aios.core.context_manager import context_manager
from aios.core.hooks import HookContext, HookPoint, hooks
from aios.core.memory import MemoryManager
from aios.core.providers import get_provider
from aios.core.providers import (
    STREAM_TOKEN, STREAM_DONE, STREAM_ERROR, STREAM_TOOL_CALL,
    LLMError, _fallback_models,
)
from aios.core.scheduler import scheduler
from aios.core.syscalls import (
    SyscallRequest, SyscallResponse, SyscallType,
    dispatcher as syscall_dispatcher, SyscallError,
)
from aios.core.tools import ToolEngine
from aios.core.tracing import start_span, end_span
from aios.db.models import Agent as AgentModel
from aios.db.models import Message

logger = logging.getLogger(__name__)


class AgentRuntime:
    """One agent loop per deployed agent.

    All LLM/memory/tool calls route through syscall dispatcher.
    Agent lifecycle managed by scheduler.
    """

    MAX_ITERATIONS = 10

    def __init__(self, agent: AgentModel, db_session_factory=None):
        self.agent = agent
        model = agent.llm_config.get("model", "openai/gpt-4o")
        self.llm = get_provider(model)
        self.tool_engine = ToolEngine(agent.tools or [])
        self.memory = MemoryManager(agent.id, llm_provider=self.llm)
        self._db_factory = db_session_factory
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

        span = start_span("agent_structured", model=self.agent.llm_config.get("model", ""))
        try:
            response = await self._llm_chat(
                messages=context,
                model=self.agent.llm_config.get("model", "openai/gpt-4o"),
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
        """Streaming: yield token/tool_call/done events as they happen."""
        scheduler.start(self.agent.id)
        hooks.fire(HookPoint.AGENT_START, HookContext(
            agent_id=self.agent.id,
            conversation_id=conversation_id,
        ))

        try:
            context = await self._build_context(conversation_id, user_message, db)
            model = self.agent.llm_config.get("model", "openai/gpt-4o")
            temp = self.agent.llm_config.get("temperature", 0.7)

            for iteration in range(self.MAX_ITERATIONS):
                tools = self.tool_engine.schemas() if self.tool_engine.tools else None

                # check cache for first iteration (no tool calls)
                if iteration == 0 and not tools:
                    cached = cache.get(context, model, temp, tools)
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
                        else:
                            cached_result = tool_cache.get(fn_name, fn_args)
                            if cached_result is not None:
                                result = cached_result
                            else:
                                try:
                                    result = await self.tool_engine.execute(fn_name, fn_args)
                                    tool_cache.set(fn_name, fn_args, result)
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
                                role="tool",
                                content=str(result)[:2000],
                                agent_id=self.agent.id,
                                tool_results={"id": tc["id"], "name": fn.get("name")},
                            ))
                    scheduler.unblock(self.agent.id)
                    yield {"type": STREAM_TOKEN, "content": "\n"}
                    continue

                # No tool calls — final response
                if response_content:
                    await self.memory.add(conversation_id, "assistant", response_content)
                    cache.set(context, model, temp, {"content": response_content, "tool_calls": None}, tools)
                    if db:
                        db.add(Message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=response_content,
                            agent_id=self.agent.id,
                        ))
                        await db.commit()
                    # save context state
                    context_manager.save(conversation_id, self.agent.id, context)

                yield {"type": STREAM_DONE}
                return

            logger.warning("Agent %s hit max iterations", self.agent.id)
            yield {"type": STREAM_TOKEN, "content": "I'm having trouble completing this request. Please try again."}
            yield {"type": STREAM_DONE}
        except Exception as e:
            logger.exception("Agent stream failed: agent=%s conv=%s", self.agent.id, conversation_id)
            hooks.fire(HookPoint.AGENT_ERROR, HookContext(
                agent_id=self.agent.id,
                conversation_id=conversation_id,
                data={"error": str(e)},
            ))
            raise
        finally:
            scheduler.terminate(self.agent.id)
            hooks.fire(HookPoint.AGENT_END, HookContext(
                agent_id=self.agent.id,
                conversation_id=conversation_id,
            ))

    async def build_context(
        self, conversation_id: str, user_message: str, db: DatabaseBackend | None = None
    ) -> list[dict]:
        return await self._build_context(conversation_id, user_message, db)

    async def _build_context(
        self, conversation_id: str, user_message: str, db: DatabaseBackend | None = None
    ) -> list[dict]:
        max_ctx = self.agent.llm_config.get("max_tokens", 4096)
        ctx = [{"role": "system", "content": self.agent.system_prompt}]

        recent = await self.memory.get_recent(conversation_id, limit=20, db=db)
        ctx.extend(recent)

        # memory pipeline: inject relevant past context
        injections = await self.memory.get_context_injections(user_message, top_k=3)
        ctx.extend(injections)

        ctx.append({"role": "user", "content": user_message})

        # enforce token budget via context manager
        ctx = context_manager.enforce_budget(ctx, max_tokens=max_ctx, reserve_tokens=max_ctx // 2)

        return ctx
