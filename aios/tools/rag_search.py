"""RAG search — governed KnowledgeRecords with permission filtering."""

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY


class RagSearchInput(BaseModel):
    query: str = Field(
        description="Pergunta em PT-BR para buscar na Base de Conhecimento governada (KnowledgeRecords com proveniência)."
    )
    top_k: int = Field(default=5, description="Quantos registros retornar (1-10)")


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
        ctx = {
            "actor_departments": set(getattr(self, "_actor_departments", None) or []),
            "is_founder": bool(getattr(self, "_is_founder", False)),
            "granted_record_ids": set(getattr(self, "_granted_record_ids", None) or []),
            "actor_user_id": actor_user_id,
            "actor_resolved": False,
            "resolution": "none",
        }
        # Caller explicitly injected scope; treat as resolved.
        if ctx["actor_departments"] or ctx["is_founder"] or ctx["granted_record_ids"]:
            ctx["actor_resolved"] = True
            ctx["resolution"] = "injected"
            return ctx
        agent_id = getattr(self, "_agent_id", "") or ""
        if not org_id:
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
            # Fail closed: no departments/grants/founder.
            return {
                "actor_departments": set(),
                "is_founder": False,
                "granted_record_ids": set(),
                "actor_user_id": actor_user_id,
                "actor_resolved": False,
                "resolution": "error_fail_closed",
            }
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
                return {
                    "ok": False,
                    "error": "actor identity unresolved; search fail-closed",
                    "query": query,
                    "results": [],
                    "count": 0,
                    "source": "knowledge_records",
                    "actor_resolution": actor.get("resolution", "none"),
                    "fail_closed": True,
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
            return {"ok": False, "error": str(e)[:500], "query": query}


TOOL_REGISTRY["rag_search"] = {"code_reference": "aios.tools.rag_search.RagSearchTool"}
# alias para compatibilidade
TOOL_REGISTRY["hybrid_search"] = TOOL_REGISTRY["rag_search"]
TOOL_REGISTRY["knowledge_search"] = TOOL_REGISTRY["rag_search"]
