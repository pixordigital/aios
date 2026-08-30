"""Team orchestration — route messages to agents by strategy."""

import asyncio
import json
import logging
from typing import AsyncGenerator

from aios.core.agent import AgentRuntime
from aios.core.providers import (
    get_provider, STREAM_TOKEN, STREAM_DONE,
)
from sqlalchemy import update

from aios.core.scheduler import scheduler
from aios.db.backend import DatabaseBackend
from aios.db.models import Team

logger = logging.getLogger(__name__)

_SUPERVISOR_SYSTEM_PROMPT = """You are a routing supervisor. Analyze the incoming message and pick the best agent from the list below.

Respond with JSON ONLY:
{"agent_index": <int>, "reason": "<why this agent>", "handoff_message": "<rephrase for the agent, include relevant context>"}

Available agents:
{agent_list}"""


class TeamOrchestrator:
    """Route incoming messages to the right agent based on strategy."""

    def __init__(self, team, agents: list, db_session_factory=None):
        self.team = team
        self.agents = agents
        self.strategy = team.routing_strategy
        self._db = db_session_factory

    async def handle_message(self, conversation_id: str, message: str, db: DatabaseBackend | None = None) -> str:
        # enqueue agent(s) for scheduling
        for a in self.agents:
            scheduler.enqueue(a.id, conv_id=conversation_id, agent_name=a.name, org_id=getattr(a, "org_id", ""))
        match self.strategy:
            case "supervisor":
                return await self._supervisor_route(conversation_id, message, db)
            case "round_robin":
                return await self._round_robin(conversation_id, message, db)
            case "broadcast":
                return await self._broadcast(conversation_id, message, db)
            case "semantic":
                return await self._semantic_route(conversation_id, message, db)
            case "hierarchical":
                return await self._hierarchical_route(conversation_id, message, db)
            case _:
                return await self._round_robin(conversation_id, message, db)

    async def handle_message_stream(
        self, conversation_id: str, message: str, db: DatabaseBackend | None = None
    ) -> AsyncGenerator[dict, None]:
        """Streaming variant — delegates to the same strategy methods."""
        match self.strategy:
            case "supervisor":
                async for ev in self._supervisor_route_stream(conversation_id, message, db):
                    yield ev
            case "round_robin":
                async for ev in self._round_robin_stream(conversation_id, message, db):
                    yield ev
            case "broadcast":
                async for ev in self._broadcast_stream(conversation_id, message, db):
                    yield ev
            case "semantic":
                async for ev in self._semantic_route_stream(conversation_id, message, db):
                    yield ev
            case "hierarchical":
                async for ev in self._hierarchical_route_stream(conversation_id, message, db):
                    yield ev
            case _:
                async for ev in self._round_robin_stream(conversation_id, message, db):
                    yield ev

    async def _shared_context_for(self, conv_id: str) -> str:
        try:
            from aios.db.engine import async_session
            from aios.db.models import Message
            from sqlalchemy import select
            async with async_session() as sess:
                rows = (await sess.execute(select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.desc()).limit(12))).scalars().all()
                if rows:
                    base = "\n".join(f"{m.role}: {m.content[:200]}" for m in reversed(rows))
                    # team vector memory: hybrid search on query
                    try:
                        if self.agents:
                            from aios.core.memory import MemoryManager
                            mm = MemoryManager(self.agents[0].id)
                            inj = await mm.get_context_injections(rows[-1].content if rows else "", top_k=2)
                            if inj:
                                base += "\n\n[Team Memory] " + inj[0]["content"]
                    except Exception:
                        pass
                    return base
        except Exception:
            pass
        return ""

    async def _hierarchical_route(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> str:
        """Orchestrator → manager → worker hierarchy if orchestrator_agent_id set."""
        if self.team.orchestrator_agent_id:
            orch = next((a for a in self.agents if a.id == self.team.orchestrator_agent_id), None)
            if orch:
                rt = AgentRuntime(orch, self._db)
                plan = await rt.run(conv_id, f"Decompose task for team: {msg}\nAgents: {', '.join(a.name for a in self.agents)}", db)
                target = next((a for a in self.agents if a.id != orch.id), self.agents[0])
                if self.team.manager_agent_id:
                    mgr = next((a for a in self.agents if a.id == self.team.manager_agent_id), None)
                    if mgr:
                        target = mgr
                return await AgentRuntime(target, self._db).run(conv_id, f"Task: {msg}\nPlan from orchestrator: {plan[:800]}", db)
        return await self._supervisor_route(conv_id, msg, db)

    async def _llm_route(self, msg: str, conv_id: str = "") -> dict:
        """Use LLM to pick the best agent. Returns dict with agent_index, reason, handoff_message."""
        shared = await self._shared_context_for(conv_id) if conv_id else ""
        agent_lines = "\n".join(
            f"[{i}] {a.name} — type:{a.agent_type} — prompt: {a.system_prompt[:800]}" for i, a in enumerate(self.agents)
        )
        if shared:
            agent_lines += f"\n\nShared team context (last 6 msgs):\n{shared}"
        llm = get_provider("openai/gpt-4o-mini")
        try:
            resp = await llm.chat_retry(
                messages=[
                    {"role": "system", "content": _SUPERVISOR_SYSTEM_PROMPT.format(agent_list=agent_lines)},
                    {"role": "user", "content": msg},
                ],
                model="openai/gpt-4o-mini",
                temperature=0.3,
                max_tokens=500,
                tools=[{
                    "type": "function",
                    "function": {
                        "name": "_route",
                        "description": "Route to best agent",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "agent_index": {"type": "integer", "description": "Index of selected agent"},
                                "reason": {"type": "string"},
                                "handoff_message": {"type": "string", "description": "Message rephrased for the agent"},
                            },
                            "required": ["agent_index", "reason", "handoff_message"],
                        },
                    },
                }],
                tool_choice={"type": "function", "function": {"name": "_route"}},
            )
            for tc in (resp.get("tool_calls") or []):
                if tc.get("function", {}).get("name") == "_route":
                    return json.loads(tc["function"]["arguments"])
        except Exception as e:
            logger.exception("LLM routing failed, falling back to agent 0")
        return {"agent_index": 0, "reason": "fallback", "handoff_message": msg}

    async def _supervisor_route(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> str:
        if not self.agents:
            return "No agents in team"
        routed = await self._llm_route(msg, conv_id)
        idx = min(routed["agent_index"], len(self.agents) - 1)
        agent = AgentRuntime(self.agents[idx], self._db)
        return await agent.run(conv_id, routed.get("handoff_message", msg), db)

    async def _supervisor_route_stream(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> AsyncGenerator[dict, None]:
        if not self.agents:
            yield {"type": STREAM_TOKEN, "content": "No agents in team"}
            yield {"type": STREAM_DONE}
            return
        routed = await self._llm_route(msg, conv_id)
        idx = min(routed["agent_index"], len(self.agents) - 1)
        yield {"type": STREAM_TOKEN, "content": f"[Routing to {self.agents[idx].name}: {routed.get('reason', '')}]\n\n"}
        agent = AgentRuntime(self.agents[idx], self._db)
        async for ev in agent.run_stream(conv_id, routed.get("handoff_message", msg), db):
            yield ev

    async def _round_robin(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> str:
        if not self.agents:
            return "No agents in team"
        extra = dict(self.team.extra_data or {})
        idx = extra.get("_rr_idx", 0)
        extra["_rr_idx"] = (idx + 1) % len(self.agents)
        self.team.extra_data = extra
        if db:
            await db.execute(update(Team).where(Team.id == self.team.id).values(extra_data=extra))
            await db.commit()
        agent = AgentRuntime(self.agents[idx], self._db)
        return await agent.run(conv_id, msg, db)

    async def _round_robin_stream(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> AsyncGenerator[dict, None]:
        if not self.agents:
            yield {"type": STREAM_TOKEN, "content": "No agents in team"}
            yield {"type": STREAM_DONE}
            return
        extra = dict(self.team.extra_data or {})
        idx = extra.get("_rr_idx", 0)
        extra["_rr_idx"] = (idx + 1) % len(self.agents)
        self.team.extra_data = extra
        if db:
            await db.execute(update(Team).where(Team.id == self.team.id).values(extra_data=extra))
            await db.commit()
        agent = AgentRuntime(self.agents[idx], self._db)
        async for ev in agent.run_stream(conv_id, msg, db):
            yield ev

    async def _broadcast(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> str:
        if not self.agents:
            return "No agents in team"
        sem = asyncio.Semaphore(5)
        async def _run_one(a):
            async with sem:
                return await AgentRuntime(a, self._db).run(conv_id, msg, db)
        results = await asyncio.gather(*(_run_one(a) for a in self.agents), return_exceptions=True)
        valid = [r for r in results if isinstance(r, str) and r.strip()]
        if not valid:
            return "All agents failed"
        try:
            judge = get_provider("openai/gpt-4o-mini")
            resp = await judge.chat_retry(messages=[{"role": "system", "content": "Pick the best answer among candidates. Return index only."}, {"role": "user", "content": "\n\n---\n\n".join(f"[{i}] {v[:600]}" for i, v in enumerate(valid))}], model="openai/gpt-4o-mini", temperature=0.2, max_tokens=10)
            idx = int((resp.get("content") or "0").strip().split()[0])
            if 0 <= idx < len(valid):
                return valid[idx]
        except Exception:
            pass
        return max(valid, key=lambda r: len(r))

    async def _broadcast_stream(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> AsyncGenerator[dict, None]:
        if not self.agents:
            yield {"type": STREAM_TOKEN, "content": "No agents in team"}
            yield {"type": STREAM_DONE}
            return
        results = await asyncio.gather(
            *(AgentRuntime(a, self._db).run(conv_id, msg, db) for a in self.agents),
            return_exceptions=True,
        )
        valid = [r for r in results if isinstance(r, str)]
        best = max(valid, key=lambda r: len(r)) if valid else ""
        yield {"type": STREAM_TOKEN, "content": best}
        yield {"type": STREAM_DONE}

    async def _semantic_route(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> str:
        try:
            from aios.core.memory import _embed
            q = _embed(msg)
            best = None
            best_score = -1
            for a in self.agents:
                e = _embed((a.system_prompt or "")[:500])
                dot = sum(x*y for x,y in zip(q,e))
                if dot > best_score:
                    best_score = dot
                    best = a
            if best:
                return await AgentRuntime(best, self._db).run(conv_id, msg, db)
        except Exception:
            pass
        return await self._supervisor_route(conv_id, msg, db)

    async def _semantic_route_stream(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> AsyncGenerator[dict, None]:
        try:
            from aios.core.memory import _embed
            q = _embed(msg)
            best = None
            best_score = -1
            for a in self.agents:
                e = _embed((a.system_prompt or "")[:500])
                dot = sum(x*y for x,y in zip(q,e))
                if dot > best_score:
                    best_score = dot
                    best = a
            if best:
                async for ev in AgentRuntime(best, self._db).run_stream(conv_id, msg, db):
                    yield ev
                return
        except Exception:
            pass
        async for ev in self._supervisor_route_stream(conv_id, msg, db):
            yield ev

    async def _hierarchical_route_stream(self, conv_id: str, msg: str, db: DatabaseBackend | None = None) -> AsyncGenerator[dict, None]:
        if self.team.orchestrator_agent_id:
            orch = next((a for a in self.agents if a.id == self.team.orchestrator_agent_id), None)
            if orch:
                yield {"type": STREAM_TOKEN, "content": f"[Hierarchical: orchestrator {orch.name} planning]\n\n"}
                rt = AgentRuntime(orch, self._db)
                plan = await rt.run(conv_id, f"Decompose: {msg}", db)
                yield {"type": STREAM_TOKEN, "content": f"[Plan] {plan[:400]}\n\n"}
                target = next((a for a in self.agents if a.id != orch.id), self.agents[0])
                async for ev in AgentRuntime(target, self._db).run_stream(conv_id, msg, db):
                    yield ev
                return
        async for ev in self._supervisor_route_stream(conv_id, msg, db):
            yield ev
