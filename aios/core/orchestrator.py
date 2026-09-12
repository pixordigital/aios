"""Team orchestration — route messages to agents by strategy."""

import asyncio
import json
import logging
from typing import AsyncGenerator

from aios.core.agent import AgentRuntime


def _get_runtime(agent, db=None):
    """Return AutonomousAgent if autonomous else AgentRuntime."""
    try:
        gov = getattr(agent, "governance_config", None) or {}
        is_auto = gov.get("autonomous", True) or gov.get("autonomy") == "autonomous"
        if is_auto:
            from aios.core.autonomous_agent import AutonomousAgent
            return AutonomousAgent(agent, db)
    except Exception:
        pass
    return AgentRuntime(agent, db)


from aios.core.providers import (
    get_provider,
    STREAM_TOKEN,
    STREAM_DONE,
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

    async def handle_message(
        self, conversation_id: str, message: str, db: DatabaseBackend | None = None
    ) -> str:
        # enqueue agent(s) for scheduling
        for a in self.agents:
            scheduler.enqueue(
                a.id,
                conv_id=conversation_id,
                agent_name=a.name,
                org_id=getattr(a, "org_id", ""),
            )
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
                async for ev in self._supervisor_route_stream(
                    conversation_id, message, db
                ):
                    yield ev
            case "round_robin":
                async for ev in self._round_robin_stream(conversation_id, message, db):
                    yield ev
            case "broadcast":
                async for ev in self._broadcast_stream(conversation_id, message, db):
                    yield ev
            case "semantic":
                async for ev in self._semantic_route_stream(
                    conversation_id, message, db
                ):
                    yield ev
            case "hierarchical":
                async for ev in self._hierarchical_route_stream(
                    conversation_id, message, db
                ):
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
                rows = (
                    (
                        await sess.execute(
                            select(Message)
                            .where(Message.conversation_id == conv_id)
                            .order_by(Message.created_at.desc())
                            .limit(12)
                        )
                    )
                    .scalars()
                    .all()
                )
                if rows:
                    base = "\n".join(
                        f"{m.role}: {m.content[:200]}" for m in reversed(rows)
                    )
                    try:
                        if self.agents:
                            from aios.core.memory import MemoryManager

                            mm = MemoryManager(self.agents[0].id)
                            inj = await mm.get_context_injections(
                                rows[-1].content if rows else "", top_k=2
                            )
                            if inj:
                                base += "\n\n[Team Memory] " + inj[0]["content"]
                    except Exception:
                        pass
                    try:
                        from aios.db.models import Team as TeamModel

                        team = await sess.get(TeamModel, self.team.id)
                        if team and team.extra_data.get("_blackboard"):
                            bb = team.extra_data["_blackboard"]
                            if isinstance(bb, dict) and bb:
                                base += (
                                    "\n\n[Blackboard] "
                                    + json.dumps(bb, ensure_ascii=False)[:800]
                                )
                    except Exception:
                        pass
                    return base
        except Exception:
            pass
        return ""

    async def update_blackboard(self, conv_id: str, key: str, value: str):
        try:
            from aios.db.engine import async_session
            from aios.db.models import Team as TeamModel

            async with async_session() as sess:
                team = await sess.get(TeamModel, self.team.id)
                if team:
                    data = dict(team.extra_data or {})
                    bb = dict(data.get("_blackboard") or {})
                    bb[key] = value[:1000]
                    data["_blackboard"] = bb
                    team.extra_data = data
                    await sess.commit()
        except Exception:
            pass

    async def _hierarchical_route(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> str:
        """
        Three-tier hierarchical handoff (non-streaming):
        1. Orchestrator receives task and creates plan
        2. Orchestrator hands off to Manager
        3. Manager hands off to appropriate agent(s)
        """
        if not self.team.orchestrator_agent_id:
            return await self._supervisor_route(conv_id, msg, db)

        orch = next(
            (a for a in self.agents if a.id == self.team.orchestrator_agent_id),
            None,
        )
        if not orch:
            return await self._supervisor_route(conv_id, msg, db)

        # Step 1: Orchestrator creates plan
        rt = _get_runtime(orch, self._db)
        plan = await rt.run(conv_id, f"Analyze this task and create a detailed execution plan. Identify which team member should handle each part. Task: {msg}", db)

        # Step 2: Orchestrator hands off to Manager
        if self.team.manager_agent_id:
            manager = next(
                (a for a in self.agents if a.id == self.team.manager_agent_id),
                None,
            )
            if manager:
                # Manager reviews plan and decides who handles what
                manager_prompt = f"""As Manager, review this plan and decide which team member should handle each part.
                
Plan from Orchestrator:
{plan}

Available team members:
{chr(10).join(f"- {a.name} (type: {a.agent_type})" for a in self.agents if a.id != orch.id and a.id != self.team.manager_agent_id)}

Respond with JSON:
{{
  "assignments": [
    {{"agent_id": "...", "task": "specific task for this agent", "reason": "why this agent"}}
  ],
  "manager_notes": "any coordination notes"
}}"""
                
                rt = _get_runtime(manager, self._db)
                manager_decision = await rt.run(conv_id, manager_prompt, db)
                
                try:
                    import json
                    decision = json.loads(manager_decision)
                    assignments = decision.get("assignments", [])
                    
                    results = []
                    for assignment in assignments:
                        agent_id = assignment.get("agent_id")
                        task = assignment.get("task", "")
                        reason = assignment.get("reason", "")
                        
                        agent = next((a for a in self.agents if a.id == agent_id), None)
                        if agent and agent.id != self.team.orchestrator_agent_id and agent.id != self.team.manager_agent_id:
                            rt = _get_runtime(agent, self._db)
                            result = await rt.run(conv_id, task, db)
                            results.append(f"[{agent.name}]: {result}")
                    
                    if results:
                        return "\n\n".join(results)
                except Exception:
                    pass
        
        # Fallback: if no manager or manager handoff fails, use supervisor
        return await self._supervisor_route(conv_id, msg, db)

    async def _llm_route(self, msg: str, conv_id: str = "") -> dict:
        """Use LLM to pick the best agent. Returns dict with agent_index, reason, handoff_message."""
        shared = await self._shared_context_for(conv_id) if conv_id else ""
        agent_lines = "\n".join(
            f"[{i}] {a.name} — type:{a.agent_type} — prompt: {a.system_prompt[:800]}"
            for i, a in enumerate(self.agents)
        )
        if shared:
            agent_lines += f"\n\nShared team context (last 6 msgs):\n{shared}"
        llm = get_provider("openai/gpt-4o-mini")
        try:
            resp = await llm.chat_retry(
                messages=[
                    {
                        "role": "system",
                        "content": _SUPERVISOR_SYSTEM_PROMPT.format(
                            agent_list=agent_lines
                        ),
                    },
                    {"role": "user", "content": msg},
                ],
                model="openai/gpt-4o-mini",
                temperature=0.3,
                max_tokens=500,
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "_route",
                            "description": "Route to best agent",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "agent_index": {
                                        "type": "integer",
                                        "description": "Index of selected agent",
                                    },
                                    "reason": {"type": "string"},
                                    "handoff_message": {
                                        "type": "string",
                                        "description": "Message rephrased for the agent",
                                    },
                                },
                                "required": [
                                    "agent_index",
                                    "reason",
                                    "handoff_message",
                                ],
                            },
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": "_route"}},
            )
            for tc in resp.get("tool_calls") or []:
                if tc.get("function", {}).get("name") == "_route":
                    return json.loads(tc["function"]["arguments"])
        except Exception as e:
            logger.exception("LLM routing failed, falling back to agent 0")
        return {"agent_index": 0, "reason": "fallback", "handoff_message": msg}

    async def _supervisor_route(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> str:
        if not self.agents:
            return "No agents in team"
        # sharding para 8+ agentes: hash conversa → shard 4
        agents = self.agents
        if len(agents) >= 8:
            import hashlib

            h = int(hashlib.md5(conv_id.encode()).hexdigest(), 16) % 4
            agents = [a for i, a in enumerate(agents) if i % 4 == h] or agents
        try:
            routed = await self._llm_route(msg, conv_id)
            idx = min(max(0, routed["agent_index"]), len(agents) - 1)
            agent = _get_runtime(agents[idx], self._db)
            out = await agent.run(conv_id, routed.get("handoff_message", msg), db)
            await self.update_blackboard(conv_id, f"last_{agents[idx].name}", out[:1000])
            try:
                from aios.core.telemetry import telemetry

                telemetry.record(agents[idx].id, getattr(agents[idx], "org_id", ""), tokens=len(out))
            except Exception:
                pass
            return out
        except Exception:
            # fallback: semantic → round_robin
            try:
                return await self._semantic_route(conv_id, msg, db)
            except Exception:
                return await self._round_robin(conv_id, msg, db)

    async def _supervisor_route_stream(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> AsyncGenerator[dict, None]:
        if not self.agents:
            yield {"type": STREAM_TOKEN, "content": "No agents in team"}
            yield {"type": STREAM_DONE}
            return
        routed = await self._llm_route(msg, conv_id)
        idx = min(routed["agent_index"], len(self.agents) - 1)
        yield {
            "type": STREAM_TOKEN,
            "content": f"[Routing to {self.agents[idx].name}: {routed.get('reason', '')}]\n\n",
        }
        agent = AgentRuntime(self.agents[idx], self._db)
        async for ev in agent.run_stream(
            conv_id, routed.get("handoff_message", msg), db
        ):
            yield ev

    async def _round_robin(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> str:
        if not self.agents:
            return "No agents in team"
        extra = dict(self.team.extra_data or {})
        idx = extra.get("_rr_idx", 0)
        extra["_rr_idx"] = (idx + 1) % len(self.agents)
        self.team.extra_data = extra
        if db:
            await db.execute(
                update(Team).where(Team.id == self.team.id).values(extra_data=extra)
            )
            await db.commit()
        agent = AgentRuntime(self.agents[idx], self._db)
        return await agent.run(conv_id, msg, db)

    async def _round_robin_stream(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> AsyncGenerator[dict, None]:
        if not self.agents:
            yield {"type": STREAM_TOKEN, "content": "No agents in team"}
            yield {"type": STREAM_DONE}
            return
        extra = dict(self.team.extra_data or {})
        idx = extra.get("_rr_idx", 0)
        extra["_rr_idx"] = (idx + 1) % len(self.agents)
        self.team.extra_data = extra
        if db:
            await db.execute(
                update(Team).where(Team.id == self.team.id).values(extra_data=extra)
            )
            await db.commit()
        agent = AgentRuntime(self.agents[idx], self._db)
        async for ev in agent.run_stream(conv_id, msg, db):
            yield ev

    async def _broadcast(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> str:
        if not self.agents:
            return "No agents in team"
        sem = asyncio.Semaphore(5)

        async def _run_one(a):
            async with sem:
                return await _get_runtime(a, self._db).run(conv_id, msg, db)

        results = await asyncio.gather(
            *(_run_one(a) for a in self.agents), return_exceptions=True
        )
        valid = [r for r in results if isinstance(r, str) and r.strip()]
        if not valid:
            return "All agents failed"
        try:
            judge = get_provider("openai/gpt-4o-mini")
            resp = await judge.chat_retry(
                messages=[
                    {
                        "role": "system",
                        "content": "Pick the best answer among candidates. Return index only.",
                    },
                    {
                        "role": "user",
                        "content": "\n\n---\n\n".join(
                            f"[{i}] {v[:600]}" for i, v in enumerate(valid)
                        ),
                    },
                ],
                model="openai/gpt-4o-mini",
                temperature=0.2,
                max_tokens=10,
            )
            idx = int((resp.get("content") or "0").strip().split()[0])
            if 0 <= idx < len(valid):
                return valid[idx]
        except Exception:
            pass
        return max(valid, key=lambda r: len(r))

    async def _broadcast_stream(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> AsyncGenerator[dict, None]:
        if not self.agents:
            yield {"type": STREAM_TOKEN, "content": "No agents in team"}
            yield {"type": STREAM_DONE}
            return
        results = await asyncio.gather(
            *(_get_runtime(a, self._db).run(conv_id, msg, db) for a in self.agents),
            return_exceptions=True,
        )
        valid = [r for r in results if isinstance(r, str)]
        best = max(valid, key=lambda r: len(r)) if valid else ""
        yield {"type": STREAM_TOKEN, "content": best}
        yield {"type": STREAM_DONE}

    async def _semantic_route(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> str:
        try:
            from aios.core.memory import _embed

            q = _embed(msg)
            best = None
            best_score = -1
            for a in self.agents:
                e = _embed((a.system_prompt or "")[:500])
                dot = sum(x * y for x, y in zip(q, e))
                if dot > best_score:
                    best_score = dot
                    best = a
            if best:
                return await _get_runtime(best, self._db).run(conv_id, msg, db)
        except Exception:
            pass
        return await self._supervisor_route(conv_id, msg, db)

    async def _semantic_route_stream(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> AsyncGenerator[dict, None]:
        try:
            from aios.core.memory import _embed

            q = _embed(msg)
            best = None
            best_score = -1
            for a in self.agents:
                e = _embed((a.system_prompt or "")[:500])
                dot = sum(x * y for x, y in zip(q, e))
                if dot > best_score:
                    best_score = dot
                    best = a
            if best:
                async for ev in AgentRuntime(best, self._db).run_stream(
                    conv_id, msg, db
                ):
                    yield ev
                return
        except Exception:
            pass
        async for ev in self._supervisor_route_stream(conv_id, msg, db):
            yield ev

    async def _hierarchical_route_stream(
        self, conv_id: str, msg: str, db: DatabaseBackend | None = None
    ) -> AsyncGenerator[dict, None]:
        """
        Three-tier hierarchical handoff:
        1. Orchestrator receives task and creates plan
        2. Orchestrator hands off to Manager
        3. Manager hands off to appropriate agent
        """
        handoff_config = self.team.handoff_config or {}
        
        if not self.team.orchestrator_agent_id:
            async for ev in self._supervisor_route_stream(conv_id, msg, db):
                yield ev
            return

        orch = next(
            (a for a in self.agents if a.id == self.team.orchestrator_agent_id),
            None,
        )
        if not orch:
            async for ev in self._supervisor_route_stream(conv_id, msg, db):
                yield ev
            return

        # Step 1: Orchestrator creates plan
        yield {
            "type": STREAM_TOKEN,
            "content": f"[Hierarchical: Orchestrator {orch.name} analyzing task]\n\n",
        }
        rt = _get_runtime(orch, self._db)
        plan = await rt.run(conv_id, f"Analyze this task and create a detailed execution plan. Identify which team member should handle each part. Task: {msg}", db)
        
        yield {"type": STREAM_TOKEN, "content": f"[Plan by {orch.name}]\n{plan[:500]}\n\n"}

        # Step 2: Orchestrator hands off to Manager
        if self.team.manager_agent_id:
            manager = next(
                (a for a in self.agents if a.id == self.team.manager_agent_id),
                None,
            )
            if manager:
                yield {
                    "type": STREAM_TOKEN,
                    "content": f"[Handoff: Orchestrator {orch.name} → Manager {manager.name}]\n\n",
                }
                
                # Manager reviews plan and decides who handles what
                manager_prompt = f"""As Manager, review this plan and decide which team member should handle each part.
                
Plan from Orchestrator:
{plan}

Available team members:
{chr(10).join(f"- {a.name} (type: {a.agent_type})" for a in self.agents if a.id != orch.id and a.id != self.team.manager_agent_id)}

Respond with JSON:
{{
  "assignments": [
    {{"agent_id": "...", "task": "specific task for this agent", "reason": "why this agent"}}
  ],
  "manager_notes": "any coordination notes"
}}"""
                
                rt = _get_runtime(manager, self._db)
                manager_decision = await rt.run(conv_id, manager_prompt, db)
                
                yield {"type": STREAM_TOKEN, "content": f"[Manager {manager.name} coordinating]\n{manager_decision[:500]}\n\n"}
                
                try:
                    import json
                    decision = json.loads(manager_decision)
                    assignments = decision.get("assignments", [])
                    
                    for assignment in assignments:
                        agent_id = assignment.get("agent_id")
                        task = assignment.get("task", "")
                        reason = assignment.get("reason", "")
                        
                        agent = next((a for a in self.agents if a.id == agent_id), None)
                        if agent and agent.id != self.team.orchestrator_agent_id and agent.id != self.team.manager_agent_id:
                            yield {
                                "type": STREAM_TOKEN,
                                "content": f"[Handoff: Manager {manager.name} → {agent.name}] {reason}\n\n",
                            }
                            
                            rt = _get_runtime(agent, self._db)
                            async for ev in agent.run_stream(conv_id, task, db):
                                yield ev
                    
                    yield {"type": STREAM_TOKEN, "content": f"[Manager {manager.name}: All tasks delegated]\n\n"}
                    return
                except Exception:
                    pass
        
        # Fallback: if no manager or manager handoff fails, use supervisor
        async for ev in self._supervisor_route_stream(conv_id, msg, db):
            yield ev
