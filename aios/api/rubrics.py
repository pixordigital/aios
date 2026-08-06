"""Rubrics API — CRUD + score responses."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aios.api.deps import get_current_user
from aios.core.rubric import rubric_manager
from aios.db.models import User

router = APIRouter(prefix="/api/rubrics", tags=["rubrics"])


class RubricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    criteria: list[str] = []
    weights: dict = {}


class RubricUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    criteria: list[str] | None = None
    weights: dict | None = None


class RubricScore(BaseModel):
    rubric_id: str
    response: str = Field(min_length=1, max_length=100000)


@router.get("")
async def list_rubrics(user: User = Depends(get_current_user)):
    return {"rubrics": rubric_manager.list()}


@router.post("")
async def create_rubric(body: RubricCreate, user: User = Depends(get_current_user)):
    rubric = rubric_manager.create(
        name=body.name,
        description=body.description,
        criteria=body.criteria,
        weights=body.weights,
    )
    return rubric


@router.put("/{rubric_id}")
async def update_rubric(rubric_id: str, body: RubricUpdate, user: User = Depends(get_current_user)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    rubric = await rubric_manager.update_rubric(rubric_id, **fields)
    if not rubric:
        raise HTTPException(404, "Rubric not found")
    return rubric


@router.delete("/{rubric_id}")
async def delete_rubric(rubric_id: str, user: User = Depends(get_current_user)):
    ok = rubric_manager.delete(rubric_id)
    if not ok:
        raise HTTPException(404, "Rubric not found")
    return {"ok": True}


@router.post("/score")
async def score_response(body: RubricScore, user: User = Depends(get_current_user)):
    return await rubric_manager.score_response(body.rubric_id, body.response)
