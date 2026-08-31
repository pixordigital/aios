from fastapi import APIRouter, Depends
from sqlalchemy import select

from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Tool
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/manifest")
async def mcp_manifest(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    rows = (
        (
            await db.execute(
                select(Tool).where(Tool.org_id == org_id, Tool.status == "active")
            )
        )
        .scalars()
        .all()
    )
    tools = []
    for t in rows:
        tools.append(
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema or {"type": "object", "properties": {}},
            }
        )
    return {"protocol": "mcp/1.0", "tools": tools, "org_id": org_id}


@router.post("/call")
async def mcp_call(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    import json

    from aios.core.tools import ToolEngine

    name = body.get("name") or body.get("tool")
    args = body.get("arguments") or body.get("args") or {}
    if not name:
        return {"ok": False, "error": "name required"}
    tool = (
        (await db.execute(select(Tool).where(Tool.org_id == org_id, Tool.name == name)))
        .scalars()
        .first()
    )
    if not tool:
        return {"ok": False, "error": "tool not found in org"}
    if tool.code_reference and tool.code_reference.startswith("code:"):
        from aios.tools.dynamic import register_dynamic_tool

        register_dynamic_tool(
            tool.name, tool.description, tool.code_reference[5:], tool.input_schema
        )
    eng = ToolEngine([name])
    try:
        out = await eng.execute(name, json.dumps(args))
        return {"ok": True, "output": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/a2a/agents")
async def a2a_agents(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    from sqlalchemy import select

    from aios.db.models import Agent

    rows = (
        (
            await db.execute(
                select(Agent).where(Agent.org_id == org_id, Agent.status == "active")
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": a.id,
            "name": a.name,
            "agent_type": a.agent_type,
            "description": a.system_prompt[:200],
            "url": f"/api/agents/{a.id}",
        }
        for a in rows
    ]
