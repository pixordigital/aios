import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from aios.core.approval_evidence import verify_and_consume_approval
from aios.core.audit import log_audit
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization, Tool
from aios.governance.ocp import DepartmentMember
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _approval_tool_args_match(*, tool_name: str, args: dict[str, Any], tool_args: Any) -> bool:
    if not isinstance(tool_args, dict):
        return False
    expected_name = str(tool_name or "")
    if "tool_name" in tool_args and str(tool_args.get("tool_name") or "") != expected_name:
        return False
    candidates = [tool_args]
    for k in ("args", "arguments", "payload", "input"):
        v = tool_args.get(k)
        if isinstance(v, dict):
            candidates.append(v)
    for cand in candidates:
        if cand == args:
            return True
        if args and all(k in cand and cand.get(k) == v for k, v in args.items()):
            if "args" in cand or "arguments" in cand or "payload" in cand or "input" in cand:
                continue
            return True
    return False


async def _tool_actor_context(db: DatabaseBackend, user) -> dict:
    """Best-effort actor identity for tool execution. Fail closed downstream if unresolved."""
    actor_departments: set[str] = set()
    is_founder = False
    try:
        rows = (
            await db.execute(
                select(DepartmentMember.department_id).where(
                    DepartmentMember.org_id == user.org_id,
                    DepartmentMember.user_id == user.id,
                )
            )
        ).scalars().all()
        actor_departments = {d for d in rows if d}
        org = await db.get(Organization, user.org_id)
        extra = (org.extra_data or {}) if org else {}
        is_founder = bool(extra.get("founder_user_id") == user.id or getattr(user, "role", "") == "owner")
    except Exception:
        pass
    granted_record_ids: set[str] = set()
    try:
        from aios.tools.rag_search import resolve_granted_record_ids

        granted_record_ids = await resolve_granted_record_ids(
            str(getattr(user, "org_id", "") or ""),
            str(getattr(user, "id", "") or ""),
            db=db,
        )
    except Exception:
        granted_record_ids = set()
    return {
        "actor_user_id": str(getattr(user, "id", "") or ""),
        "actor_departments": actor_departments,
        "is_founder": is_founder,
        "granted_record_ids": granted_record_ids,
    }


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
    approval_action_id = body.get("approval_action_id")
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
    actor = await _tool_actor_context(db, user)
    eng = ToolEngine([name], org_id=org_id, **actor)
    try:
        out = await eng.execute(name, json.dumps(args))
        return {"ok": True, "output": out}
    except Exception as e:
        logger.exception("MCP tool call failed org=%s tool=%s", org_id, name)
        msg = str(e)
        if "HITL/action policy" in msg or "requires approval" in msg:
            if not approval_action_id:
                return {"ok": False, "error": msg, "requires_approval": True}
            approval = await verify_and_consume_approval(
                db,
                org_id=str(org_id),
                approval_action_id=str(approval_action_id),
                expected_tool_name=str(name),
                args_match=lambda tool_args: _approval_tool_args_match(tool_name=str(name), args=args, tool_args=tool_args),
            )
            audit_details = {
                "reason": msg,
                "tool_name": str(name),
                "approval_action_id": approval_action_id,
                **dict(approval.details),
            }
            if not approval.ok:
                await log_audit(
                    db, org_id, "mcp.call.blocked", "tool",
                    user_id=getattr(user, "id", None),
                    resource_id=str(getattr(tool, "id", "") or name),
                    details=audit_details,
                )
                await db.commit()
                return {"ok": False, "error": msg, "requires_approval": True, "approval_reason": approval.reason}
            await log_audit(
                db, org_id, "mcp.call.approval_consumed", "tool",
                user_id=getattr(user, "id", None),
                resource_id=str(getattr(tool, "id", "") or name),
                details=audit_details,
            )
            await db.commit()
            try:
                out = await eng.execute(name, json.dumps(args), approved=True)
                return {"ok": True, "output": out}
            except Exception as e2:
                logger.exception("MCP approved tool call failed org=%s tool=%s", org_id, name)
                return {"ok": False, "error": str(e2)}
        return {"ok": False, "error": "Tool execution failed"}


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
