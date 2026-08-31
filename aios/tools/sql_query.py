import logging
import re
from pydantic import BaseModel, Field
from sqlalchemy import text

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class SQLQueryInput(BaseModel):
    query: str = Field(description="SQL SELECT only, ex: SELECT count(*) FROM agents")
    limit: int = Field(default=50, description="max rows")


class SQLQueryTool(BaseTool):
    name = "sql_query"
    description = "Executa SQL SELECT read-only no Postgres (máx 50 linhas). Bloqueia INSERT/UPDATE/DELETE."

    async def run(self, query: str, limit: int = 50) -> dict:
        q = query.strip()
        if not re.match(r"^\s*SELECT\b", q, re.I):
            return {"error": "only SELECT allowed"}
        if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", q, re.I):
            return {"error": "write operations blocked"}
        q = q.rstrip(";") + f" LIMIT {min(limit, 100)}"
        try:
            from aios.db.engine import async_session

            async with async_session() as s:
                rows = await s.execute(text(q))
                cols = list(rows.keys())
                data = [dict(zip(cols, r)) for r in rows.fetchall()]
                return {
                    "ok": True,
                    "columns": cols,
                    "rows": data[:limit],
                    "count": len(data),
                }
        except Exception as e:
            logger.warning("sql_query failed: %s", e)
            return {"error": str(e)[:500]}


TOOL_REGISTRY["sql_query"] = {"code_reference": "aios.tools.sql_query.SQLQueryTool"}
