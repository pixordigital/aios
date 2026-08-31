from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aios.core.tools import ToolEngine
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Tool
from aios.schemas import BaseModel
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolOut(BaseModel):
    id: str
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    code_reference: str
    is_builtin: bool
    status: str


class ToolCreate(BaseModel):
    name: str
    description: str = ""
    input_schema: dict = {}
    output_schema: dict = {}
    code_reference: str = ""


@router.post("", response_model=ToolOut)
async def create_tool(
    body: ToolCreate,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    existing = await db.execute(
        select(Tool).where(Tool.org_id == org_id, Tool.name == body.name)
    )
    if existing.scalars().first():
        raise HTTPException(409, detail=f"tool {body.name} already exists in this org")
    tool = Tool(
        org_id=org_id,
        name=body.name,
        description=body.description,
        input_schema=body.input_schema,
        output_schema=body.output_schema,
        code_reference=body.code_reference,
    )
    db.add(tool)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, detail="tool name conflict")
        raise
    await db.refresh(tool)
    if tool.code_reference and tool.code_reference.startswith("code:"):
        from aios.tools.dynamic import register_dynamic_tool
        try:
            register_dynamic_tool(tool.name, tool.description, tool.code_reference[5:], tool.input_schema)
        except Exception:
            pass
    return tool


@router.get("", response_model=list[ToolOut])
async def list_tools(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    result = await db.execute(
        select(Tool)
        .where(Tool.org_id == org_id)
        .order_by(Tool.name)
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.get("/audit/calls")
async def tool_audit_calls(user=Depends(get_current_user)):
    """Get tool call audit counters (in-memory, since app start)."""
    return ToolEngine.audit_summary()


@router.post("/{tool_id}/test")
async def test_tool(
    tool_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    tool = await db.get(Tool, tool_id)
    if not tool or tool.org_id != org_id:
        raise HTTPException(404)
    args = body.get("args") or body.get("arguments") or {}
    import json
    from aios.core.tools import ToolEngine
    if tool.code_reference and tool.code_reference.startswith("code:"):
        from aios.tools.dynamic import register_dynamic_tool
        register_dynamic_tool(tool.name, tool.description, tool.code_reference[5:], tool.input_schema)
    eng = ToolEngine([tool.name])
    try:
        out = await eng.execute(tool.name, json.dumps(args))
        return {"ok": True, "output": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/{tool_id}", response_model=ToolOut)
async def get_tool(
    tool_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    tool = await db.get(Tool, tool_id)
    if not tool or tool.org_id != org_id:
        raise HTTPException(404)
    return tool
