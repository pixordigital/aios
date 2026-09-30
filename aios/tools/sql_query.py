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

    # App tables carrying secrets or cross-org PII. The tool runs without an
    # org context, so it cannot scope rows — these tables are off-limits
    # entirely. An agent (or a prompt-injected inbound message) could otherwise
    # SELECT api keys, tokens and other orgs' contacts with one query.
    _DENY_APP_TABLES = (
        "users", "credentials", "channel_connections", "oauth_accounts",
        "invitations", "organizations", "whatsapp_contacts", "pending_approvals",
    )

    _DENY_APP_PATTERN = re.compile(
        r"(?:FROM|JOIN|UPDATE|INTO)\s+(" + "|".join(_DENY_APP_TABLES) + r")\b",
        re.IGNORECASE,
    )

    # Tables whose rows belong to one org. When the engine knows the caller's
    # org, a query touching these must filter to exactly that org — an
    # unscoped SELECT would otherwise return every org's rows.
    _ORG_SCOPED_TABLES = (
        "agents", "conversations", "messages", "teams", "budgets",
        "workflows", "crm_deals", "memories", "artifacts", "skills",
        "voice_recordings", "usage_records",
    )

    _ORG_SCOPED_PATTERN = re.compile(
        r"(?:FROM|JOIN)\s+(" + "|".join(_ORG_SCOPED_TABLES) + r")\b",
        re.IGNORECASE,
    )
    _ORG_LITERAL_PATTERN = re.compile(r"org_id\s*=\s*'([^']+)'", re.IGNORECASE)

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
        # deny credential/PII tables: no org context, so no safe way to scope rows
        if self._DENY_APP_PATTERN.search(q):
            return {"error": "tabela com segredos/PII bloqueada para SQL direto; use a ferramenta do canal"}
        # org scoping: a query touching org-owned tables must filter to the
        # caller's org and no other. This is a guardrail, not a SQL parser —
        # it kills unscoped whole-table reads, the realistic exfil path.
        if self._ORG_SCOPED_PATTERN.search(q):
            mine = getattr(self, "_org_id", "") or ""
            lits = self._ORG_LITERAL_PATTERN.findall(q)
            if not mine or not lits or any(o != mine for o in lits):
                return {"error": "adicione WHERE org_id = '<sua org>' à consulta"}
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
