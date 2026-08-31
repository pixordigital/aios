import logging
from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class LeadScoreInput(BaseModel):
    email: str
    company_size: str = Field(default="", description="1-10|11-50|51-200|200+")
    budget: str = Field(default="", description="baixo|medio|alto")
    timeline: str = Field(default="", description="imediato|30d|90d|indefinido")
    pain: str = Field(default="", description="dor principal")


class LeadScoringTool(BaseTool):
    name = "lead_score"
    description = "Score BANT 0-100 para MQL→SQL. Retorna score, stage e recomendação."

    async def run(
        self,
        email: str,
        company_size: str = "",
        budget: str = "",
        timeline: str = "",
        pain: str = "",
    ) -> dict:
        score = 0
        reasons = []
        if company_size in ("51-200", "200+"):
            score += 30
            reasons.append("porte ideal")
        elif company_size in ("11-50"):
            score += 15
        if budget == "alto":
            score += 30
            reasons.append("budget alto")
        elif budget == "medio":
            score += 15
        if timeline == "imediato":
            score += 25
            reasons.append("timeline imediato")
        elif timeline == "30d":
            score += 15
        if pain:
            score += 15
            reasons.append("dor mapeada")
        stage = "sql" if score >= 60 else "mql" if score >= 30 else "disqualified"
        rec = (
            "encaminhar para Closer"
            if stage == "sql"
            else "nutrir"
            if stage == "mql"
            else "descartar"
        )
        return {
            "email": email,
            "score": score,
            "stage": stage,
            "recommendation": rec,
            "reasons": reasons,
        }


TOOL_REGISTRY["lead_score"] = {
    "code_reference": "aios.tools.lead_scoring.LeadScoringTool"
}
