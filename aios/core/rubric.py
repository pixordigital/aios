"""Rubric evaluation — score agent responses against quality criteria.

Rubrics encode expectations (tone, accuracy, completeness, safety).
Used by the meta-agent to evaluate and improve agent performance.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Rubric:
    id: str
    name: str
    description: str = ""
    criteria: list[str] = field(default_factory=list)
    weights: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class RubricManager:
    """Manage rubrics and score responses against them."""

    def __init__(self):
        self._rubrics: dict[str, Rubric] = {}

    def create(self, name: str, description: str = "",
               criteria: list[str] = None, weights: dict = None) -> Rubric:
        import uuid
        rubric = Rubric(
            id=str(uuid.uuid4())[:8],
            name=name,
            description=description,
            criteria=criteria or [],
            weights=weights or {},
        )
        self._rubrics[rubric.id] = rubric
        return rubric

    def get(self, rubric_id: str) -> Rubric | None:
        return self._rubrics.get(rubric_id)

    def list(self) -> list[Rubric]:
        return list(self._rubrics.values())

    def delete(self, rubric_id: str) -> bool:
        return self._rubrics.pop(rubric_id, None) is not None

    async def score_response(self, rubric_id: str, response: str,
                             llm_provider=None) -> dict:
        """Score a response against rubric criteria (0-10 each).

        Uses LLM if available, else heuristic (length + keyword match).
        """
        rubric = self._rubrics.get(rubric_id)
        if not rubric:
            return {"error": "Rubric not found"}

        if llm_provider:
            try:
                return await self._score_with_llm(rubric, response, llm_provider)
            except Exception:
                logger.exception("LLM scoring failed, using heuristic")
        return self._score_heuristic(rubric, response)

    async def _score_with_llm(self, rubric: Rubric, response: str,
                              llm_provider) -> dict:
        criteria_text = "\n".join(f"- {c}" for c in rubric.criteria)
        llm_response = await llm_provider.chat(
            messages=[
                {"role": "system", "content": (
                    f"You are an evaluator. Score this response 0-10 for each criterion:\n"
                    f"{criteria_text}\n"
                    'Return JSON: {"scores": {"criterion": score}, "notes": "..."}'
                )},
                {"role": "user", "content": response[:2000]},
            ],
            model="openai/gpt-4o-mini",
            max_tokens=300,
        )
        import json as _json
        raw = llm_response.get("content", "")
        try:
            parsed = _json.loads(raw)
        except _json.JSONDecodeError:
            return self._score_heuristic(rubric, response)
        scores = parsed.get("scores", {})
        total = sum(scores.values()) / max(len(scores), 1)
        return {
            "rubric_id": rubric.id,
            "total_score": round(total, 1),
            "scores": scores,
            "notes": parsed.get("notes", ""),
        }

    def _score_heuristic(self, rubric: Rubric, response: str) -> dict:
        """Fallback: length + criterion keyword presence."""
        scores = {}
        words = set(response.lower().split())
        for criterion in rubric.criteria:
            keywords = [w for w in criterion.lower().split() if len(w) > 4]
            hits = sum(1 for k in keywords if k in words)
            base = min(10, len(response) // 200)
            scores[criterion] = round(min(10, base + hits * 2), 1)
        total = sum(scores.values()) / max(len(scores), 1)
        return {
            "rubric_id": rubric.id,
            "total_score": round(total, 1),
            "scores": scores,
            "notes": "heuristic scoring (no LLM)",
        }

    async def update_rubric(self, rubric_id: str, **fields) -> Rubric | None:
        rubric = self._rubrics.get(rubric_id)
        if not rubric:
            return None
        for k, v in fields.items():
            if v is not None and hasattr(rubric, k):
                setattr(rubric, k, v)
        return rubric


rubric_manager = RubricManager()
