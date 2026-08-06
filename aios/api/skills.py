"""Skills API — CRUD + search for reusable agent patterns."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aios.api.deps import get_current_user
from aios.core.skills import skill_store
from aios.db.models import User

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillCreate(BaseModel):
    agent_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    skill_type: str = "tool_pattern"
    content: str = ""
    input_schema: dict = {}
    tags: list[str] = []


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    tags: list[str] | None = None


@router.get("")
async def list_skills(
    agent_id: str = "",
    q: str = "",
    user: User = Depends(get_current_user),
):
    skills = await skill_store.list(agent_id=agent_id, q=q)
    return {"skills": skills}


@router.post("")
async def create_skill(
    body: SkillCreate,
    user: User = Depends(get_current_user),
):
    skill = await skill_store.create(
        agent_id=body.agent_id,
        org_id=user.org_id,
        name=body.name,
        description=body.description,
        skill_type=body.skill_type,
        content=body.content,
        input_schema=body.input_schema,
        tags=body.tags,
    )
    return skill


@router.put("/{skill_id}")
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    user: User = Depends(get_current_user),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    skill = await skill_store.update(skill_id, **fields)
    if not skill:
        raise HTTPException(404, "Skill not found")
    return skill


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    user: User = Depends(get_current_user),
):
    ok = await skill_store.delete(skill_id)
    if not ok:
        raise HTTPException(404, "Skill not found")
    return {"ok": True}


@router.post("/{skill_id}/apply")
async def apply_skill(
    skill_id: str,
    user: User = Depends(get_current_user),
):
    """Increment usage count and return skill content for injection."""
    skill = await skill_store.get(skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    await skill_store.increment_usage(skill_id)
    return {
        "skill_id": skill.id,
        "name": skill.name,
        "content": skill.content,
        "description": skill.description,
    }
