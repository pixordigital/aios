"""RAG search — Base de Conhecimento (PDFs do cliente)."""

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY


class RagSearchInput(BaseModel):
    query: str = Field(description="Pergunta em PT-BR para buscar na Base de Conhecimento (PDFs, FAQs, políticas, catálogo)")
    top_k: int = Field(default=5, description="Quantos chunks retornar (1-10)")


class RagSearchTool(BaseTool):
    name = "rag_search"
    description = "Busca RAG na Base de Conhecimento do cliente (PDFs carregados em /dashboard/files → Base de Conhecimento). Use para tabela de preços, FAQ, políticas, catálogo, manuais. Retorna chunks com source e score. Sempre cite a fonte."
    input_model = RagSearchInput

    async def run(self, query: str, top_k: int = 5) -> dict:
        # The org comes from the running agent (ToolEngine sets `_org_id`), never
        # from `select(Organization).limit(1)`: that returned whichever tenant was
        # first in the table, so one tenant's agent retrieved another tenant's
        # knowledge chunks. Empty org = no context, not "some org".
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
            from aios.core.rag import hybrid_search
            results = await hybrid_search(
                org_id, query, top_k=min(max(top_k, 1), 10),
                agent_id=getattr(self, "_agent_id", "") or "",
            )
            return {"ok": True, "query": query, "results": results, "count": len(results)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:500], "query": query}


TOOL_REGISTRY["rag_search"] = {"code_reference": "aios.tools.rag_search.RagSearchTool"}
# alias para compatibilidade
TOOL_REGISTRY["hybrid_search"] = TOOL_REGISTRY["rag_search"]
TOOL_REGISTRY["knowledge_search"] = TOOL_REGISTRY["rag_search"]
