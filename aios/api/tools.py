from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.db.engine import get_db
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
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    result = await db.execute(
        select(Tool)
        .where(Tool.org_id == org_id)
        .order_by(Tool.name)
    )
    return result.scalars().all()


@router.get("/{tool_id}", response_model=ToolOut)
async def get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    tool = await db.get(Tool, tool_id)
    if not tool or tool.org_id != org_id:
        raise HTTPException(404)
    return tool
