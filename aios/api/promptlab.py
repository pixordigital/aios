import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Agent

router = APIRouter(prefix="/api/promptlab", tags=["promptlab"])


class PromptTestRequest(BaseModel):
    agent_id: str | None = None
    system_prompt: str
    user_input: str
    model: str = "openai/gpt-4o-mini"
    temperature: float = 0.7
    compare_prompt: str | None = None


@router.post("/test")
async def test_prompt(
    body: PromptTestRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    from aios.core.providers import get_provider

    llm = get_provider(body.model)
    start = time.time()
    try:
        resp = await llm.chat_retry(
            messages=[
                {"role": "system", "content": body.system_prompt},
                {"role": "user", "content": body.user_input},
            ],
            model=body.model,
            temperature=body.temperature,
            max_tokens=800,
        )
        out = resp.get("content", "")
        lat = int((time.time() - start) * 1000)
        result = {"output": out, "latency_ms": lat}
        if body.compare_prompt:
            start2 = time.time()
            resp2 = await llm.chat_retry(
                messages=[
                    {"role": "system", "content": body.compare_prompt},
                    {"role": "user", "content": body.user_input},
                ],
                model=body.model,
                temperature=body.temperature,
                max_tokens=800,
            )
            result["compare_output"] = resp2.get("content", "")
            result["compare_latency_ms"] = int((time.time() - start2) * 1000)
        return result
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/agent/{agent_id}/ab")
async def ab_test_agent(
    agent_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    prompt_a = body.get("prompt_a") or agent.system_prompt
    prompt_b = body.get("prompt_b")
    if not prompt_b:
        raise HTTPException(400, detail="prompt_b required")
    inp = body.get("input") or "Hello"
    from aios.core.agent import AgentRuntime
    import copy

    cfg_a = copy.copy(agent)
    cfg_a.system_prompt = prompt_a
    cfg_b = copy.copy(agent)
    cfg_b.system_prompt = prompt_b
    out_a = await AgentRuntime(cfg_a).run(f"ab_{agent_id}_a", inp, db)
    out_b = await AgentRuntime(cfg_b).run(f"ab_{agent_id}_b", inp, db)
    return {"a": out_a[:3000], "b": out_b[:3000]}
