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


class SkillImportUrl(BaseModel):
    url: str = Field(min_length=5, max_length=2000)
    agent_id: str = Field(min_length=1, max_length=36)


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


@router.post("/import-url")
async def import_skill_from_url(
    body: SkillImportUrl,
    user: User = Depends(get_current_user),
):
    """Import skill from internet URL (GitHub raw, skills.sh, gist, etc)."""
    import re
    import httpx

    url = body.url.strip()
    # Convert GitHub blob to raw
    if "github.com" in url and "/blob/" in url:
        url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    # skills.sh -> raw
    if "skills.sh" in url:
        # try to fetch raw via skills.sh API or direct
        pass

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "AIOS-Skill-Importer/1.0"})
            if resp.status_code != 200:
                raise HTTPException(400, f"Falha ao buscar URL: {resp.status_code} {resp.text[:500]}")
            raw = resp.text
            # limit size
            if len(raw) > 200000:
                raise HTTPException(400, "Arquivo muito grande (>200k)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Erro ao buscar URL: {e}")

    # Try parse as JSON first
    import json
    name = ""
    description = ""
    content = ""
    skill_type = "tool_pattern"
    tags = []
    input_schema = {}

    raw_strip = raw.strip()
    if raw_strip.startswith("{") and raw_strip.endswith("}"):
        try:
            data = json.loads(raw_strip)
            name = data.get("name", "") or data.get("title", "")
            description = data.get("description", "")
            content = data.get("content", "") or data.get("prompt", "") or data.get("body", "")
            skill_type = data.get("skill_type", "tool_pattern")
            tags = data.get("tags", [])
            input_schema = data.get("input_schema", {})
            if not content and isinstance(data, dict):
                content = raw_strip[:5000]
        except Exception:
            pass

    if not content:
        # Try frontmatter markdown: ---\nname: ...\n---\ncontent
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
        if fm_match:
            fm_raw, body_md = fm_match.groups()
            # simple yaml parse for name/description
            for line in fm_raw.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    v = v.strip().strip('"').strip("'")
                    if k == "name":
                        name = v
                    elif k == "description":
                        description = v
                    elif k in ("skill_type", "type"):
                        skill_type = v
                    elif k == "tags":
                        # tags: [a, b] or a, b
                        v = v.strip("[]")
                        tags = [t.strip().strip('"').strip("'") for t in v.split(",") if t.strip()]
            content = body_md.strip()
        else:
            # Plain markdown: use filename from URL as name
            content = raw.strip()
            # try to extract title from first # heading
            m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            if m:
                name = m.group(1).strip()[:100]
            if not name:
                # fallback to URL last part
                name = url.split("/")[-1].split("?")[0].split("#")[0][:100] or "imported-skill"
                name = re.sub(r"\.(md|json|txt)$", "", name)

    if not name:
        name = url.split("/")[-1][:100] or "imported-skill"
    if not description:
        description = f"Importado de {url[:100]}"

    # Clean up
    name = name.strip()[:255]
    description = description.strip()[:1000]
    content = content.strip()[:50000]
    if not content:
        raise HTTPException(400, "Conteúdo vazio após parse")

    skill = await skill_store.create(
        agent_id=body.agent_id,
        org_id=user.org_id,
        name=name,
        description=description,
        skill_type=skill_type,
        content=content,
        input_schema=input_schema,
        tags=tags,
    )
    return {"ok": True, "skill_id": skill.id, "name": skill.name, "url": url}
