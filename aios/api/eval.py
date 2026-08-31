import csv
import io
import json
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from aios.api.deps import get_current_user, get_org_id
from aios.core.agent import AgentRuntime
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Agent

router = APIRouter(prefix="/api/agents", tags=["eval"])


class EvalCase(BaseModel):
    input: str
    expected: str | None = None


class EvalRequest(BaseModel):
    cases: list[EvalCase]
    judge_model: str = "openai/gpt-4o-mini"


class EvalResult(BaseModel):
    input: str
    output: str
    expected: str | None = None
    score: float | None = None
    latency_ms: int


@router.post("/{agent_id}/eval")
async def eval_agent(
    agent_id: str,
    body: EvalRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    runtime = AgentRuntime(agent)
    results = []
    for case in body.cases[:20]:
        start = time.time()
        out = await runtime.run(f"eval_{agent_id}", case.input, db)
        latency = int((time.time() - start) * 1000)
        score = None
        if case.expected:
            try:
                from aios.core.providers import get_provider

                judge = get_provider(body.judge_model)
                resp = await judge.chat_retry(
                    messages=[
                        {
                            "role": "system",
                            "content": 'Score 0-1 whether output matches expected. Return JSON {"score":0.0-1.0}',
                        },
                        {
                            "role": "user",
                            "content": f"Expected: {case.expected}\nOutput: {out[:2000]}",
                        },
                    ],
                    model=body.judge_model,
                    temperature=0.0,
                    max_tokens=100,
                )
                txt = resp.get("content", "")
                score = float(json.loads(txt).get("score", 0)) if "{" in txt else 0.0
            except (ValueError, json.JSONDecodeError, KeyError):
                score = 1.0 if case.expected.lower() in out.lower() else 0.0
        results.append(
            EvalResult(
                input=case.input,
                output=out[:4000],
                expected=case.expected,
                score=score,
                latency_ms=latency,
            )
        )
    avg = sum(r.score for r in results if r.score is not None) / max(
        1, len([r for r in results if r.score is not None])
    )
    avg_r = round(avg, 3)
    try:
        from aios.db.models import EvalRun

        er = EvalRun(
            agent_id=agent_id,
            org_id=org_id,
            judge_model=body.judge_model,
            avg_score=avg_r,
            results=[r.model_dump() for r in results],
        )
        db.add(er)
        await db.commit()
        await db.refresh(er)
        eval_id = er.id
    except Exception:
        eval_id = None
    return {
        "agent_id": agent_id,
        "avg_score": avg_r,
        "eval_run_id": eval_id,
        "results": [r.model_dump() for r in results],
    }


@router.get("/{agent_id}/eval/history")
async def eval_history(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    from sqlalchemy import select

    from aios.db.models import EvalRun

    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    rows = (
        (
            await db.execute(
                select(EvalRun)
                .where(EvalRun.agent_id == agent_id)
                .order_by(EvalRun.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "avg_score": r.avg_score,
            "judge_model": r.judge_model,
            "created_at": str(r.created_at),
            "cases": len(r.results or []),
        }
        for r in rows
    ]


@router.post("/{agent_id}/datasets")
async def create_dataset(
    agent_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    from aios.db.models import Dataset

    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    ds = Dataset(
        agent_id=agent_id,
        org_id=org_id,
        name=body.get("name", "default"),
        cases=body.get("cases", [])[:100],
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return ds


@router.post("/{agent_id}/datasets/upload")
async def upload_dataset_csv(
    agent_id: str,
    file: UploadFile = File(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except Exception:
        raise HTTPException(400, detail="invalid encoding")
    reader = csv.DictReader(io.StringIO(text))
    cases = []
    for row in reader:
        inp = row.get("input") or row.get("prompt") or row.get("query") or ""
        exp = row.get("expected") or row.get("output") or ""
        if inp:
            cases.append(
                {"input": inp.strip(), "expected": exp.strip() if exp else None}
            )
        if len(cases) >= 200:
            break
    if not cases:
        raise HTTPException(400, detail="csv empty or missing input column")
    from aios.db.models import Dataset

    ds = Dataset(
        agent_id=agent_id,
        org_id=org_id,
        name=file.filename or "csv-upload",
        cases=cases,
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return ds


@router.get("/{agent_id}/datasets")
async def list_datasets(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    from sqlalchemy import select

    from aios.db.models import Dataset

    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    rows = (
        (await db.execute(select(Dataset).where(Dataset.agent_id == agent_id)))
        .scalars()
        .all()
    )
    return rows
