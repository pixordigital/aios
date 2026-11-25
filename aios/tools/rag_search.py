"""RAG search — governed KnowledgeRecords with permission filtering."""

import logging

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class RagSearchInput(BaseModel):
    query: str = Field(
        description="Pergunta em PT-BR para buscar na Base de Conhecimento governada (KnowledgeRecords com proveniência)."
    )
    top_k: int = Field(default=5, description="Quantos registros retornar (1-10)")


async def resolve_granted_record_ids(org_id: str, actor_user_id: str, db=None) -> set[str]:
    """Best-effort DB resolve of active knowledge grants for actor user in org.

    Returns empty set when no grant model exists or resolution fails.
    Fail-closed: callers should treat empty as no explicit confidential grants.
    """
    if not org_id or not actor_user_id:
        logger.debug(
            "rag_search.grants_skipped reason=missing_identity org_present=%s actor_present=%s",
            bool(org_id),
            bool(actor_user_id),
        )
        return set()
    try:
        from sqlalchemy import inspect as sa_inspect, select

        GrantModel = None
        for mod_path, attr in (
            ("aios.governance.knowledge", "KnowledgeGrant"),
            ("aios.governance.knowledge", "KnowledgeRecordGrant"),
            ("aios.db.models", "KnowledgeGrant"),
            ("aios.db.models", "KnowledgeRecordGrant"),
        ):
            try:
                mod = __import__(mod_path, fromlist=[attr])
                candidate = getattr(mod, attr, None)
                if candidate is not None:
                    GrantModel = candidate
                    break
            except Exception:
                continue
        if GrantModel is None:
            logger.debug("rag_search.grants_unavailable org=%s actor=%s", org_id, actor_user_id)
            return set()

        mapper = sa_inspect(GrantModel)
        cols = {c.key for c in mapper.column_attrs}
        conditions = []
        if "org_id" in cols:
            conditions.append(getattr(GrantModel, "org_id") == org_id)
        user_col = None
        for name in ("user_id", "actor_user_id", "grantee_user_id", "subject_user_id"):
            if name in cols:
                user_col = name
                break
        if user_col is None:
            logger.debug("rag_search.grants_unavailable reason=no_user_col org=%s actor=%s", org_id, actor_user_id)
            return set()
        conditions.append(getattr(GrantModel, user_col) == actor_user_id)
        if "revoked_at" in cols:
            conditions.append(getattr(GrantModel, "revoked_at").is_(None))
        if "active" in cols:
            conditions.append(getattr(GrantModel, "active").is_(True))
        if "is_active" in cols:
            conditions.append(getattr(GrantModel, "is_active").is_(True))
        record_col = None
        for name in ("record_id", "knowledge_record_id", "knowledge_id", "resource_id"):
            if name in cols:
                record_col = name
                break
        if record_col is None:
            logger.debug("rag_search.grants_unavailable reason=no_record_col org=%s actor=%s", org_id, actor_user_id)
            return set()

        now = None
        if "expires_at" in cols or "valid_until" in cols:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).replace(tzinfo=None)
        if "expires_at" in cols:
            exp = getattr(GrantModel, "expires_at")
            conditions.append((exp.is_(None)) | (exp >= now))
        if "valid_until" in cols:
            vu = getattr(GrantModel, "valid_until")
            conditions.append((vu.is_(None)) | (vu >= now))
        if "valid_from" in cols and now is not None:
            vf = getattr(GrantModel, "valid_from")
            conditions.append((vf.is_(None)) | (vf <= now))

        stmt = select(getattr(GrantModel, record_col)).where(*conditions)
        if db is None:
            from aios.db.engine import async_session

            async with async_session() as s:
                rows = (await s.execute(stmt)).scalars().all()
        else:
            rows = (await db.execute(stmt)).scalars().all()
        grants = {str(r) for r in rows if r}
        logger.debug("rag_search.grants_resolved org=%s actor=%s count=%s", org_id, actor_user_id, len(grants))
        return grants
    except Exception:
        logger.warning(
            "rag_search.grants_resolution_failed org=%s actor=%s fail_closed=true",
            org_id,
            actor_user_id,
            exc_info=True,
        )
        return set()


class RagSearchTool(BaseTool):
    name = "rag_search"
    description = (
        "Busca permission-aware em KnowledgeRecords governados (fonte da verdade com "
        "proveniência/citação). Filtra por tenant/departamento/classificação. "
        "Sempre cite citation/source_type/source_id."
    )
    input_model = RagSearchInput

    async def _resolve_actor_context(self, org_id: str) -> dict:
        """Best-effort actor context. Fail closed on any resolution error."""
        actor_user_id = str(getattr(self, "_actor_user_id", "") or "")
        actor_resolved_flag = bool(getattr(self, "_actor_resolved", False))
        ctx = {
            "actor_departments": set(getattr(self, "_actor_departments", None) or []),
            "is_founder": bool(getattr(self, "_is_founder", False)),
            "granted_record_ids": set(getattr(self, "_granted_record_ids", None) or []),
            "actor_user_id": actor_user_id,
            "actor_resolved": False,
            "resolution": "none",
        }
        # Caller/ToolEngine already resolved scope. Honor it to avoid redundant DB
        # actor/grant lookups. Conservative: skip only when scope is already
        # sufficient (depts/founder/grants injected/resolved). actor_user_id-only
        # is not enough to know depts/grants, so keep DB resolution path.
        injected_scope = bool(
            ctx["actor_departments"] or ctx["is_founder"] or ctx["granted_record_ids"]
        )
        if actor_resolved_flag and injected_scope:
            ctx["actor_resolved"] = True
            ctx["resolution"] = "injected"
            return ctx
        agent_id = getattr(self, "_agent_id", "") or ""
        if injected_scope and not actor_user_id:
            ctx["actor_resolved"] = True
            ctx["resolution"] = "injected"
            return ctx
        if not org_id:
            if injected_scope:
                ctx["actor_resolved"] = True
                ctx["resolution"] = "injected"
            return ctx
        try:
            from sqlalchemy import select

            from aios.db.engine import async_session
            from aios.db.models import Organization, User
            from aios.governance.ocp import DepartmentMember

            async with async_session() as s:
                if agent_id:
                    rows = (
                        await s.execute(
                            select(DepartmentMember.department_id).where(
                                DepartmentMember.org_id == org_id,
                                DepartmentMember.member_type == "agent",
                                DepartmentMember.agent_id == agent_id,
                            )
                        )
                    ).scalars().all()
                    ctx["actor_departments"] = {d for d in rows if d}
                    ctx["actor_resolved"] = True
                    ctx["resolution"] = "agent_departments"

                if actor_user_id:
                    user = (
                        await s.execute(
                            select(User).where(User.id == actor_user_id, User.org_id == org_id)
                        )
                    ).scalars().first()
                    if user is not None:
                        org = await s.get(Organization, org_id)
                        extra = (org.extra_data or {}) if org else {}
                        ctx["is_founder"] = bool(
                            extra.get("founder_user_id") == user.id or user.role == "owner"
                        )
                        rows = (
                            await s.execute(
                                select(DepartmentMember.department_id).where(
                                    DepartmentMember.org_id == org_id,
                                    DepartmentMember.user_id == user.id,
                                )
                            )
                        ).scalars().all()
                        ctx["actor_departments"] |= {d for d in rows if d}
                        ctx["actor_resolved"] = True
                        ctx["resolution"] = "user_identity"
        except Exception:
            logger.warning(
                "rag_search.actor_resolution_failed org=%s agent=%s actor=%s fail_closed=true",
                org_id,
                agent_id,
                actor_user_id,
                exc_info=True,
            )
            # Fail closed: no departments/grants/founder.
            return {
                "actor_departments": set(),
                "is_founder": False,
                "granted_record_ids": set(),
                "actor_user_id": actor_user_id,
                "actor_resolved": False,
                "resolution": "error_fail_closed",
            }

        # DB grants are additive, best-effort. Never grant on resolver errors.
        if actor_user_id and not ctx["granted_record_ids"]:
            try:
                ctx["granted_record_ids"] = await resolve_granted_record_ids(org_id, actor_user_id)
            except Exception:
                ctx["granted_record_ids"] = set()
        if injected_scope and ctx["actor_resolved"] is False:
            ctx["actor_resolved"] = True
            ctx["resolution"] = "injected"
        return ctx

    async def run(self, query: str, top_k: int = 5) -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {
                "ok": False,
                "error": "sem org no contexto; a busca fica restrita a base deste agente",
                "query": query,
                "results": [],
                "count": 0,
            }
        try:
            from aios.core.rag import search_knowledge_records

            actor = await self._resolve_actor_context(org_id)
            # Fail closed when no actor scope/identity can be resolved. Returning
            # unfiltered results would leak restricted/confidential records.
            has_scope = bool(
                actor["actor_departments"]
                or actor["is_founder"]
                or actor["granted_record_ids"]
                or actor.get("actor_user_id")
            )
            if not actor.get("actor_resolved") and not has_scope:
                logger.warning(
                    "rag_search.fail_closed reason=unresolved_actor org=%s resolution=%s has_actor_user_id=%s",
                    org_id,
                    actor.get("resolution", "none"),
                    bool(actor.get("actor_user_id")),
                )
                return {
                    "ok": False,
                    "error": "actor identity unresolved; search fail-closed",
                    "query": query,
                    "results": [],
                    "count": 0,
                    "source": "knowledge_records",
                    "actor_resolution": actor.get("resolution", "none"),
                    "fail_closed": True,
                    "missing_actor_context": [
                        "actor_user_id",
                        "actor_departments",
                        "is_founder",
                        "granted_record_ids",
                    ],
                    "remediation": (
                        "Inject actor identity into ToolEngine/caller context "
                        "(actor_user_id or actor_departments/is_founder/granted_record_ids). "
                        "Knowledge search stays fail-closed without resolvable scope."
                    ),
                }
            results = await search_knowledge_records(
                org_id,
                query,
                top_k=min(max(top_k, 1), 10),
                actor_departments=actor["actor_departments"],
                is_founder=actor["is_founder"],
                granted_record_ids=actor["granted_record_ids"],
            )
            return {
                "ok": True,
                "query": query,
                "results": results,
                "count": len(results),
                "source": "knowledge_records",
                "actor_resolution": actor.get("resolution", "unknown"),
            }
        except Exception as e:
            logger.warning(
                "rag_search.error org=%s agent=%s actor=%s resolution=%s",
                org_id,
                getattr(self, "_agent_id", "") or "",
                getattr(self, "_actor_user_id", "") or "",
                locals().get("actor", {}).get("resolution", "unknown") if isinstance(locals().get("actor"), dict) else "unknown",
                exc_info=True,
            )
            return {"ok": False, "error": str(e)[:500], "query": query, "results": [], "count": 0}


TOOL_REGISTRY["rag_search"] = {"code_reference": "aios.tools.rag_search.RagSearchTool"}
# alias para compatibilidade
TOOL_REGISTRY["hybrid_search"] = TOOL_REGISTRY["rag_search"]
TOOL_REGISTRY["knowledge_search"] = TOOL_REGISTRY["rag_search"]
