"""Meta agent API — eval history, run eval, apply improvement."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aios.api.deps import get_current_user, get_db_backend
from aios.core.meta_agent import meta_agent
from aios.core.rubric import rubric_manager
from aios.db.backend import DatabaseBackend
from aios.db.models import User

router = APIRouter(prefix="/api/meta", tags=["meta"])


class EvalRequest(BaseModel):
    agent_id: str
    task: str = Field(min_length=1, max_length=10000)
    response: str = Field(min_length=1, max_length=100000)
    rubric_id: str = ""


class ApplyRequest(BaseModel):
    agent_id: str
    suggestion: str = Field(min_length=1, max_length=2000)


@router.post("/eval")
async def run_eval(body: EvalRequest, user: User = Depends(get_current_user)):
    """Score a response against rubric and generate suggestions."""
    return await meta_agent.evaluate(
        agent_id=body.agent_id,
        task=body.task,
        response=body.response,
        rubric_id=body.rubric_id,
    )


@router.get("/history")
async def eval_history(
    agent_id: str = "",
    user: User = Depends(get_current_user),
):
    return {"evals": meta_agent.history(agent_id)}


@router.get("/suggest")
async def get_suggestions(
    agent_id: str,
    user: User = Depends(get_current_user),
):
    return await meta_agent.suggest_improvement(agent_id)


@router.post("/apply")
async def apply_improvement(
    body: ApplyRequest,
    user: User = Depends(get_current_user),
    db: DatabaseBackend = Depends(get_db_backend),
):
    result = await meta_agent.apply_improvement(body.agent_id, body.suggestion, db=db)
    if not result.get("applied"):
        raise HTTPException(404, result.get("error", "Failed to apply"))
    return result
