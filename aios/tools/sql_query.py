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
    description = "Executa SQL SELECT read-only no Postgres (máx 100 linhas). Bloqueia INSERT/UPDATE/DELETE e tabelas de sistema."

    _DENY_TABLES = (
        "pg_catalog", "pg_shadow", "pg_authid", "pg_auth_members", "pg_roles",
        "pg_user", "pg_group", "pg_database", "pg_tablespace", "pg_class",
        "pg_attribute", "pg_index", "pg_constraint", "pg_trigger", "pg_proc",
        "pg_type", "pg_namespace", "pg_stat_activity", "pg_stat_database",
        "pg_stat_user_tables", "pg_locks", "pg_prepared_xacts", "pg_replication_slots",
        "information_schema", "pg_extension", "pg_available_extensions",
        "pg_seclabels", "pg_shseclabel", "pg_shdescription", "pg_collation",
        "pg_conversion", "pg_language", "pg_largeobject", "pg_largeobject_metadata",
        "pg_opclass", "pg_operator", "pg_opfamily", "pg_partitioned_table",
        "pg_policy", "pg_publication", "pg_publication_rel", "pg_range",
        "pg_rewrite", "pg_sequence", "pg_subscription", "pg_subscription_rel",
        "pg_tablespace", "pg_ts_config", "pg_ts_dict", "pg_ts_parser",
        "pg_ts_template", "pg_enum", "pg_cast", "pg_depend", "pg_init_privs",
        "pg_inherits", "pg_partitioned_table", "pg_replication_origin"
    )

    _DENY_PATTERN = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in _DENY_TABLES) + r")\b",
        re.IGNORECASE
    )

    async def run(self, query: str, limit: int = 50) -> dict:
        q = query.strip()
        if not re.match(r"^\s*SELECT\b", q, re.I):
            return {"error": "only SELECT allowed"}
        if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|VACUUM|ANALYZE)\b", q, re.I):
            return {"error": "write operations blocked"}
        # deny system catalog tables
        if self._DENY_PATTERN.search(q):
            return {"error": "acesso a tabelas de sistema bloqueado"}
        # deny pg_* table references in FROM/JOIN
        if re.search(r"(?:FROM|JOIN)\s+pg_\w+", q, re.I):
            return {"error": "tabelas pg_* bloqueadas"}
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
