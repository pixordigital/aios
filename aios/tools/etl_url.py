"""ETL URL → RAG — coleta blog/site e indexa na Base de Conhecimento."""

import logging
import re

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class EtlUrlInput(BaseModel):
    url: str = Field(description="URL do blog/site para coletar e indexar (WordPress/Medium/Substack)")
    max_pages: int = Field(default=3, description="Máx de páginas/links a seguir (1-5)")


class EtlUrlTool(BaseTool):
    name = "etl_url"
    description = "ETL URL → RAG: coleta conteúdo de URL/blog e indexa na Base de Conhecimento (chunk 800 + embedding). Use quando cliente fornece URL do site/blog ao invés de PDF. Suporta WordPress/Medium/Substack."
    input_model = EtlUrlInput

    async def run(self, url: str, max_pages: int = 3) -> dict:
        if not re.match(r"^https?://", url):
            return {"ok": False, "error": "URL deve começar com http:// ou https://"}
        max_pages = max(1, min(5, int(max_pages or 3)))
        try:
            import httpx
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "AIOS-ETL/1.0"}) as c:
                r = await c.get(url)
                if r.status_code != 200:
                    return {"ok": False, "error": f"fetch {r.status_code}", "url": url}
                html = r.text
                soup = BeautifulSoup(html, "html.parser")
                # remove script/style
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)[:30000]
                # tenta achar links internos para max_pages >1 (simples)
                links = []
                if max_pages > 1:
                    for a in soup.find_all("a", href=True)[:20]:
                        href = a["href"]
                        if href.startswith("/") and url.rstrip("/") in href or href.startswith(url):
                            links.append(href if href.startswith("http") else url.rstrip("/") + href)
                    links = list(dict.fromkeys(links))[: max_pages - 1]
                    for link in links:
                        try:
                            rr = await c.get(link)
                            if rr.status_code == 200:
                                ss = BeautifulSoup(rr.text, "html.parser")
                                for t in ss(["script", "style"]):
                                    t.decompose()
                                text += "\n\n" + ss.get_text(separator="\n", strip=True)[:10000]
                        except Exception:
                            continue
                # chunk + embed + save como Memory
                chunks = [text[i : i + 800] for i in range(0, len(text), 800)][:30]
                try:
                    from aios.db.engine import async_session
                    from sqlalchemy import select
                    from aios.db.models import Organization, Memory, Agent
                    from aios.core.memory import _embed

                    async with async_session() as s:
                        org = (await s.execute(select(Organization).limit(1))).scalars().first()
                        if not org:
                            return {"ok": False, "error": "org not found"}
                        ag = (await s.execute(select(Agent).where(Agent.org_id == org.id).limit(1))).scalars().first()
                        agent_id = ag.id if ag else "00000000-0000-0000-0000-000000000000"
                        for ch in chunks:
                            try:
                                emb = _embed(ch)
                            except Exception:
                                emb = None
                            m = Memory(
                                agent_id=agent_id,
                                org_id=org.id,
                                type="long_term",
                                content=ch,
                                extra_data={"source": url, "embedding": emb} if emb else {"source": url},
                            )
                            s.add(m)
                        await s.commit()
                except Exception as e:
                    logger.warning("etl_url save failed %s", e)
                    return {"ok": False, "error": str(e)[:300], "url": url, "chunks": len(chunks)}
                return {"ok": True, "url": url, "chunks": len(chunks), "chars": len(text), "pages": 1 + len(links)}
        except ImportError:
            return {"ok": False, "error": "beautifulsoup4 não instalado: pip install beautifulsoup4"}
        except Exception as e:
            logger.exception("etl_url failed")
            return {"ok": False, "error": str(e)[:500], "url": url}


TOOL_REGISTRY["etl_url"] = {"code_reference": "aios.tools.etl_url.EtlUrlTool"}
TOOL_REGISTRY["collect-blog"] = TOOL_REGISTRY["etl_url"]
