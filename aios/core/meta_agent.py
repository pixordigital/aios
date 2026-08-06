"""Meta agent — self-improvement via eval loop → score → rewrite.

Task agent does work. Meta agent evaluates against rubrics,
suggests improvements, and can apply them to agent config.
"""

import logging
import time
from dataclasses import dataclass, field

from aios.db.models import Agent

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    id: str
    agent_id: str
    task: str
    response: str
    total_score: float
    scores: dict
    suggestions: list[str]
    created_at: float = field(default_factory=time.time)


class MetaAgent:
    """Evaluate and improve agent performance."""

    def __init__(self):
        self._history: list[EvalResult] = []
        self._max_history = 100

    async def evaluate(self, agent_id: str, task: str, response: str,
                       rubric_id: str = "", llm_provider=None) -> dict:
        """Run eval loop: score response, generate suggestions."""
        import uuid
        from aios.core.rubric import rubric_manager

        if rubric_id:
            scoring = await rubric_manager.score_response(rubric_id, response, llm_provider)
            scores = scoring.get("scores", {})
            total = scoring.get("total_score", 0)
        else:
            # default heuristic rubric
            rubric = rubric_manager.create(
                name="default",
                description="Default evaluation rubric",
                criteria=["relevant", "accurate", "helpful", "clear", "complete"],
            )
            scoring = await rubric_manager.score_response(rubric.id, response, llm_provider)
            scores = scoring.get("scores", {})
            total = scoring.get("total_score", 0)

        suggestions = await self._suggest_improvements(task, response, total, llm_provider)

        result = EvalResult(
            id=str(uuid.uuid4())[:8],
            agent_id=agent_id,
            task=task,
            response=response[:2000],
            total_score=total,
            scores=scores,
            suggestions=suggestions,
        )
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return {
            "eval_id": result.id,
            "agent_id": agent_id,
            "total_score": total,
            "scores": scores,
            "suggestions": suggestions,
        }

    async def _suggest_improvements(self, task: str, response: str, score: float,
                                    llm_provider=None) -> list[str]:
        """Generate improvement suggestions for the agent."""
        suggestions = []
        if score < 5:
            suggestions.append("Increase response specificity — include concrete details and examples.")
        if len(response) < 100:
            suggestions.append("Expand response length — provide more complete reasoning.")
        if score < 7 and llm_provider:
            try:
                llm_response = await llm_provider.chat(
                    messages=[
                        {"role": "system", "content": "You are a meta-agent. Suggest 2-3 concrete improvements to make this agent response better. Return a JSON list of strings."},
                        {"role": "user", "content": f"Task: {task}\nResponse: {response[:1000]}"},
                    ],
                    model="openai/gpt-4o-mini",
                    max_tokens=200,
                )
                import json as _json
                raw = llm_response.get("content", "")
                try:
                    parsed = _json.loads(raw)
                    if isinstance(parsed, list):
                        suggestions = [str(s) for s in parsed[:3]]
                except _json.JSONDecodeError:
                    pass
            except Exception:
                logger.exception("LLM suggestion generation failed")
        return suggestions or ["Review response for clarity and completeness."]

    async def suggest_improvement(self, agent_id: str, llm_provider=None) -> dict:
        """Aggregate suggestions from recent evals for an agent."""
        evals = [e for e in self._history if e.agent_id == agent_id]
        if not evals:
            return {"agent_id": agent_id, "suggestions": [], "avg_score": None}
        suggestions = []
        for e in evals[-10:]:
            suggestions.extend(e.suggestions)
        avg = sum(e.total_score for e in evals) / len(evals)
        return {
            "agent_id": agent_id,
            "suggestions": suggestions[:5],
            "avg_score": round(avg, 1),
            "eval_count": len(evals),
        }

    async def apply_improvement(self, agent_id: str, suggestion: str,
                                db=None) -> dict:
        """Apply a suggestion to the agent's system prompt."""
        if not db:
            return {"applied": False, "error": "No DB provided"}
        agent = await db.get(Agent, agent_id)
        if not agent:
            return {"applied": False, "error": "Agent not found"}
        old_prompt = agent.system_prompt
        agent.system_prompt = old_prompt + f"\n\n[Improvement] {suggestion}"
        await db.commit()
        return {
            "applied": True,
            "agent_id": agent_id,
            "suggestion": suggestion,
            "prompt_before": old_prompt[:200],
            "prompt_after": agent.system_prompt[:200],
        }

    def history(self, agent_id: str = "") -> list[dict]:
        evals = [e for e in self._history if (not agent_id or e.agent_id == agent_id)]
        return [
            {
                "id": e.id,
                "agent_id": e.agent_id,
                "task": e.task[:200],
                "total_score": e.total_score,
                "scores": e.scores,
                "suggestions": e.suggestions,
                "created_at": e.created_at,
            }
            for e in evals[-20:]
        ]


meta_agent = MetaAgent()
