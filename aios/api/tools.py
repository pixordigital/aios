from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aios.core.tools import ToolEngine
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Tool
from aios.schemas import BaseModel
from .deps import get_org_id

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
    tool = Tool(
        org_id=org_id,
        name=body.name,
        description=body.description,
        input_schema=body.input_schema,
        output_schema=body.output_schema,
        code_reference=body.code_reference,
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
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
async def tool_audit_calls():
    """Get tool call audit counters (in-memory, since app start)."""
    return ToolEngine.audit_summary()


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
