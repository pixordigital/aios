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
        ctx = {
            "actor_departments": set(getattr(self, "_actor_departments", None) or []),
            "is_founder": bool(getattr(self, "_is_founder", False)),
            "granted_record_ids": set(getattr(self, "_granted_record_ids", None) or []),
        }
        # Caller explicitly injected context; trust only positive scope narrowing attrs.
        if ctx["actor_departments"] or ctx["is_founder"] or ctx["granted_record_ids"]:
            return ctx
        agent_id = getattr(self, "_agent_id", "") or ""
        if not org_id:
            return ctx
        try:
            from sqlalchemy import select

            from aios.db.engine import async_session
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
                # No user identity on tool; founder stays False (fail closed).
        except Exception:
            # Fail closed: no departments/grants/founder.
            return {
                "actor_departments": set(),
                "is_founder": False,
                "granted_record_ids": set(),
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
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:500], "query": query}


TOOL_REGISTRY["rag_search"] = {"code_reference": "aios.tools.rag_search.RagSearchTool"}
# alias para compatibilidade
TOOL_REGISTRY["hybrid_search"] = TOOL_REGISTRY["rag_search"]
TOOL_REGISTRY["knowledge_search"] = TOOL_REGISTRY["rag_search"]
