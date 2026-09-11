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
        # org_id: tenta pegar do contexto, senão primeiro org
        org_id = ""
        try:
            from aios.db.engine import async_session
            from sqlalchemy import select
            from aios.db.models import Organization
            async with async_session() as s:
                org = (await s.execute(select(Organization).limit(1))).scalars().first()
                if org:
                    org_id = org.id
        except Exception:
            pass
        # fallback: usa hybrid_search sem org (será filtrado se org_id vazio)
        try:
            from aios.core.rag import hybrid_search
            # tenta com org_id, se falhar tenta sem
            results = await hybrid_search(org_id, query, top_k=min(max(top_k, 1), 10))
            if not results and org_id:
                # tenta sem filtro org para debug
                results = await hybrid_search("", query, top_k)
            return {"ok": True, "query": query, "results": results, "count": len(results)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:500], "query": query}


TOOL_REGISTRY["rag_search"] = {"code_reference": "aios.tools.rag_search.RagSearchTool"}
# alias para compatibilidade
TOOL_REGISTRY["hybrid_search"] = TOOL_REGISTRY["rag_search"]
TOOL_REGISTRY["knowledge_search"] = TOOL_REGISTRY["rag_search"]
