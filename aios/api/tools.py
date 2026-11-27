import importlib
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aios.core.approval_evidence import verify_and_consume_approval
from aios.core.audit import log_audit
from aios.core.tools import ToolEngine
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Organization, Tool
from aios.governance.ocp import DepartmentMember
from aios.schemas import BaseModel, PageResponse
from .deps import get_current_user, get_org_id, verify_org_access_async

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
    dynamic: bool = False


def _is_dynamic_or_code_tool(*, code_reference: str = "", dynamic: bool = False) -> bool:
    return bool(dynamic or (code_reference or "").startswith("code:"))


async def _require_tool_admin(db: DatabaseBackend, user, org_id: str) -> None:
    role = getattr(user, "role", "")
    if role in {"admin", "org_admin", "owner", "superadmin"}:
        return
    try:
        org = await db.get(Organization, org_id)
        extra = (org.extra_data or {}) if org else {}
        if extra.get("founder_user_id") == getattr(user, "id", None):
            return
    except Exception:
        pass
    if db is not None and org_id:
        source = "api.tools.require_tool_admin"
        try:
            from aios.governance.security import record_security_event

            event = await record_security_event(
                db,
                org_id=str(org_id),
                source=source,
                event_type="security.authz.denied",
                severity="medium",
                actor_type="human",
                actor_id=str(getattr(user, "id", "") or "") or None,
                payload={"reason": "tool_admin_required", "path_source": source},
            )
            if event is not None:
                await db.commit()
        except Exception:
            logging.getLogger(__name__).debug("authz denied metric skipped", exc_info=True)
    raise HTTPException(403, "admin, owner, or founder role required for dynamic/code tools")


@router.post("", response_model=ToolOut)
async def create_tool(
    body: ToolCreate,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    if _is_dynamic_or_code_tool(code_reference=body.code_reference, dynamic=body.dynamic):
        await _require_tool_admin(db, user, org_id)
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


@router.get("", response_model=PageResponse[ToolOut])
async def list_tools(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items = (await db.execute(
        select(Tool)
        .where(Tool.org_id == org_id)
        .order_by(Tool.name)
        .limit(limit + 1)
        .offset(offset)
    )).scalars().all()
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    next_cursor = str(offset + limit) if has_more else None
    total = (await db.execute(
        select(__import__('sqlalchemy').func.count(Tool.id)).where(Tool.org_id == org_id)
    )).scalar()
    return PageResponse(items=items, next_cursor=next_cursor, has_more=has_more, total=total)


@router.get("/audit/calls")
async def tool_audit_calls(user=Depends(get_current_user)):
    """Get tool call audit counters (in-memory, since app start)."""
    return ToolEngine.audit_summary()


def _approval_tool_args_match(*, tool_name: str, args: dict[str, Any], tool_args: Any) -> bool:
    if not isinstance(tool_args, dict):
        return False
    # Accept exact args or common wrapper shapes; reject mismatched explicit fields.
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
        # Subset match when args are explicit; extra metadata keys allowed.
        if args and all(k in cand and cand.get(k) == v for k, v in args.items()):
            # Avoid matching obvious wrappers with different nested payload.
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


async def _direct_tool_hitl_reason(db: DatabaseBackend, user, org_id: str, tool_name: str, args) -> str:
    """Agent HITL policy for direct tool calls; no org context blocks execution."""
    if not org_id or str(getattr(user, "org_id", "") or "") != str(org_id):
        return "org context missing"
    try:
        org = await db.get(Organization, org_id)
        extra = org.extra_data if isinstance(getattr(org, "extra_data", None), dict) else {}
        gov = extra.get("governance_config")
        cfg = {**extra, **(gov if isinstance(gov, dict) else {})}
        from types import SimpleNamespace
        from aios.core.agent import AgentRuntime

        # Direct calls have no agent opt-out; baseline thresholds always apply.
        policy = SimpleNamespace(
            _hitl_enabled=True,
            _hitl_tools=set(cfg.get("hitl_tools") or []),
            _hitl_value_threshold=float(cfg.get("hitl_value_threshold", 5000) or 0),
            _hitl_discount_threshold=float(cfg.get("hitl_discount_threshold", 10) or 0),
        )
        return AgentRuntime._hitl_tool_reason(policy, tool_name, args)
    except Exception:
        return "org policy unavailable"


def registry_entries() -> list[dict]:
    """Code registry as builder metadata: name, description, input schema.

    The single source of truth for the flow builder palette, the node modal
    tool list, and save-time validation. Built from TOOL_REGISTRY (populated
    by importing aios.tools), so a tool that exists in code but was never
    wired in cannot appear — and a palette entry can never name a tool that
    fails at run time with "Unknown tool". Entries that fail to instantiate
    are skipped, never fatal to the whole list.
    """
    import aios.tools  # noqa: F401 — importing populates the registry
    from aios.tools.registry import TOOL_REGISTRY

    log = logging.getLogger(__name__)
    out = []
    for name in sorted(TOOL_REGISTRY):
        try:
            mod_path = TOOL_REGISTRY[name]["code_reference"]
            mod = importlib.import_module(mod_path.rsplit(".", 1)[0])
            tool = getattr(mod, mod_path.rsplit(".", 1)[1])()
            schema = tool.openai_schema().get("function", {})
            out.append({
                "name": name,
                "description": getattr(tool, "description", "") or "",
                "input_schema": (schema.get("parameters") or {}),
            })
        except Exception:
            log.warning("registry entry %s skipped", name, exc_info=True)
    return out


@router.get("/registry")
async def tool_registry(user=Depends(get_current_user)):
    """Builder metadata for every runnable code tool."""
    return {"tools": registry_entries()}


@router.post("/{tool_id}/test")
async def test_tool(
    tool_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    tool = await db.get(Tool, tool_id)
    if not org_id or str(getattr(user, "org_id", "") or "") != str(org_id):
        return {"ok": False, "error": "HITL: org context missing", "requires_approval": True}
    await verify_org_access_async(org_id, tool, db=db, actor_id=user.id, source="api.tools.test_tool")
    args = body.get("args") or body.get("arguments") or {}
    approval_action_id = body.get("approval_action_id")
    if tool.code_reference and tool.code_reference.startswith("code:"):
        from aios.tools.dynamic import register_dynamic_tool
        register_dynamic_tool(tool.name, tool.description, tool.code_reference[5:], tool.input_schema)
    reason = await _direct_tool_hitl_reason(db, user, org_id, tool.name, args)
    approval_consumed = False

    async def _consume(reason_text: str):
        nonlocal approval_consumed
        if approval_consumed:
            return True, "ok"
        if not approval_action_id:
            return False, "approval_action_id required"
        approval = await verify_and_consume_approval(
            db,
            org_id=str(org_id),
            approval_action_id=str(approval_action_id),
            expected_tool_name=str(tool.name),
            args_match=lambda tool_args: _approval_tool_args_match(tool_name=str(tool.name), args=args, tool_args=tool_args),
        )
        audit_details = {
            "reason": reason_text,
            "tool_name": tool.name,
            "approval_action_id": approval_action_id,
            **dict(approval.details),
        }
        if not approval.ok:
            await log_audit(
                db, org_id, "tools.test.blocked", "tool",
                user_id=getattr(user, "id", None),
                resource_id=str(tool_id),
                details=audit_details,
            )
            await db.commit()
            return False, approval.reason
        approval_consumed = True
        await log_audit(
            db, org_id, "tools.test.approval_consumed", "tool",
            user_id=getattr(user, "id", None),
            resource_id=str(tool_id),
            details=audit_details,
        )
        await db.commit()
        return True, "ok"

    if reason:
        ok, approval_reason = await _consume(reason)
        if not ok:
            return {"ok": False, "error": f"HITL: {reason}", "requires_approval": True, "approval_reason": approval_reason}

    import json
    from aios.core.tools import ToolEngine
    actor = await _tool_actor_context(db, user)
    eng = ToolEngine([tool.name], org_id=org_id, **actor)
    try:
        out = await eng.execute(tool.name, json.dumps(args), approved=bool(reason) or approval_consumed)
        return {"ok": True, "output": out}
    except Exception as e:
        msg = str(e)
        if "HITL/action policy" in msg or "requires approval" in msg:
            ok, approval_reason = await _consume(msg)
            if not ok:
                return {"ok": False, "error": msg, "requires_approval": True, "approval_reason": approval_reason}
            try:
                out = await eng.execute(tool.name, json.dumps(args), approved=True)
                return {"ok": True, "output": out}
            except Exception as e2:
                return {"ok": False, "error": str(e2)}
        return {"ok": False, "error": msg}


@router.get("/{tool_id}", response_model=ToolOut)
async def get_tool(
    tool_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    tool = await db.get(Tool, tool_id)
    await verify_org_access_async(org_id, tool, db=db, actor_id=user.id, source="api.tools.get_tool")
    return tool
