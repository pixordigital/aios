"""Agent runtime — think → act → observe → respond loop."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from aios.config import settings
from aios.core.providers import get_provider
from aios.core.memory import MemoryManager
from aios.core.tools import ToolEngine
from aios.db.models import Agent as AgentModel
from aios.db.models import Conversation, Message

logger = logging.getLogger(__name__)


class AgentRuntime:
    """One agent loop per deployed agent."""

    MAX_ITERATIONS = 10

    def __init__(self, agent: AgentModel, db_session_factory=None):
        self.agent = agent
        model = agent.llm_config.get("model", "openai/gpt-4o")
        self.llm = get_provider(model)
        self.tool_engine = ToolEngine(agent.tools or [])
        self.memory = MemoryManager(agent.id)
        self._db_factory = db_session_factory

    async def run(
        self,
        conversation_id: str,
        user_message: str,
        db: AsyncSession | None = None,
    ) -> str:
        context = await self._build_context(conversation_id, user_message, db)

        for iteration in range(self.MAX_ITERATIONS):
            response = await self.llm.chat(
                messages=context,
                model=self.agent.llm_config.get("model", "openai/gpt-4o"),
                temperature=self.agent.llm_config.get("temperature", 0.7),
                max_tokens=self.agent.llm_config.get("max_tokens", 4096),
                tools=self.tool_engine.schemas() if self.tool_engine.tools else None,
            )

            if response.get("tool_calls"):
                context.append({
                    "role": "assistant",
                    "content": response.get("content") or "",
                    "tool_calls": response["tool_calls"],
                })
                for tc in response["tool_calls"]:
                    fn = tc.get("function", {})
                    result = await self.tool_engine.execute(
                        fn.get("name"), fn.get("arguments", "{}")
                    )
                    context.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": result,
                    })
                    if db:
                        db.add(Message(
                            conversation_id=conversation_id,
                            role="tool",
                            content=result[:2000],
                            agent_id=self.agent.id,
                            tool_results={"id": tc["id"], "name": fn.get("name")},
                        ))
                continue

            final = response.get("content") or ""
            await self.memory.add(conversation_id, "assistant", final)

            if db:
                db.add(Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=final,
                    agent_id=self.agent.id,
                ))
                await db.commit()

            return final

        logger.warning("Agent %s hit max iterations", self.agent.id)
        return "I'm having trouble completing this request. Please try again."

    async def _build_context(
        self, conversation_id: str, user_message: str, db: AsyncSession | None = None
    ) -> list[dict]:
        ctx = [{"role": "system", "content": self.agent.system_prompt}]

        recent = await self.memory.get_recent(conversation_id, limit=20, db=db)
        ctx.extend(recent)

        ctx.append({"role": "user", "content": user_message})
        return ctx
