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
    input_model = SQLQueryInput
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

    # Guards below run against a sanitised copy of the query. A naive regex over
    # the raw text is defeated by comments ("1=1 /* org_id='mine' */"), string
    # literals, and quoted identifiers -- so masking them first is what makes the
    # org-scope check meaningful.
    _COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
    _STRING_RE = re.compile(r"'(?:[^']|'')*'")

    @classmethod
    def _mask(cls, q: str) -> str:
        """Hide comments AND string bodies, preserving length so offsets line up.

        Used for keyword analysis (FROM/JOIN/OR/UNION), where a keyword quoted
        inside a string must not be counted as structure.
        """
        return cls._STRING_RE.sub(
            lambda m: "'" + "_" * max(0, len(m.group(0)) - 2) + "'" if len(m.group(0)) >= 2 else "''",
            cls._COMMENT_RE.sub(lambda m: " " * len(m.group(0)), q),
        )

    @classmethod
    def _strip_comments(cls, q: str) -> str:
        """Hide comments only, keeping string literals intact.

        org_id literal extraction needs this: a commented-out ``org_id='x'`` is
        not part of the query, so it must not be read as "references another org"
        and must not be mistaken for the real predicate.
        """
        return cls._COMMENT_RE.sub(lambda m: " " * len(m.group(0)), q)

    # Identifiers may be quoted ("agents") or schema-qualified (public.agents).
    # Both are valid SQL and both name the same table, so a keyword pattern
    # matched on the raw text let `SELECT * FROM "messages"` and
    # `FROM public.users` walk straight past both the org-scope check and the
    # secret-table deny-list. Normalise the identifier instead of the text.
    _TABLE_REF_RE = re.compile(
        r"(?:\bFROM\b|\bJOIN\b|\bINTO\b|\bUPDATE\b)\s+"
        r"((?:\"[^\"]+\"|[A-Za-z_][\w$]*)"
        r"(?:\s*\.\s*(?:\"[^\"]+\"|[A-Za-z_][\w$]*))*)",
        re.IGNORECASE,
    )

    @classmethod
    def _referenced_tables(cls, q: str) -> set[str]:
        """Lower-cased bare table names in FROM/JOIN/INTO/UPDATE position.

        Quoting and schema qualification are stripped, so `"agents"`,
        `public.agents` and `agents` all collapse to `agents`.
        """
        names: set[str] = set()
        for raw in cls._TABLE_REF_RE.findall(q):
            last = raw.split(".")[-1].strip()
            names.add(last.strip('"').strip("`").lower())
        return names

    # A WHERE clause that can only ever narrow: it must constrain org_id with a
    # literal comparison, and must not contain OR / UNION / OR-with-true, any of
    # which would let the org_id predicate be bypassed by a sibling condition.
    _UNION_RE = re.compile(r"\bUNION\b", re.IGNORECASE)
    _OR_RE = re.compile(r"\bOR\b", re.IGNORECASE)
    # bare true / 1=1 style always-true predicates
    _ALWAYS_TRUE_RE = re.compile(r"\btrue\b|\b1\s*=\s*1\b", re.IGNORECASE)
    _SUBQUERY_RE = re.compile(r"\(\s*\s*SELECT\b", re.IGNORECASE)
    _NOT_EQUALS_RE = re.compile(r"org_id\s*(<>|!=)", re.IGNORECASE)
    _IN_LIKE_RE = re.compile(r"org_id\s+(IN|LIKE|ILIKE|BETWEEN)\b", re.IGNORECASE)

    def _check_org_scope(self, q: str) -> str | None:
        """Return an error string when `q` could return another org's rows.

        The previous check only asserted that a literal org_id equal to the
        caller's appeared *somewhere*. That is trivially defeated -- every one of
        these passed while returning every org's data:

            WHERE org_id = 'mine' OR 1=1
            WHERE org_id = 'mine' OR true
            SELECT ... WHERE org_id='mine' UNION ALL SELECT ... FROM agents

        A predicate only constrains the result if nothing can widen it again, so
        this rejects OR, UNION, subqueries, always-true predicates and any
        org_id test that is not a plain equality against the caller's org.
        """
        mine = getattr(self, "_org_id", "") or ""
        if not mine:
            return "org_id do chamador desconhecido; consulta a dados de outra org bloqueada"
        masked = self._mask(q)
        # Literals are read from the comment-stripped query, so a commented-out
        # org_id is neither trusted as the predicate nor flagged as a foreign org.
        code = self._strip_comments(q)
        lits = self._ORG_LITERAL_PATTERN.findall(code)
        if not lits:
            return "adicione WHERE org_id = '<sua org>' à consulta"
        if any(o != mine for o in lits):
            return "consulta referencia org_id de outra organizacao"
        # Equalities are fine; every other org_id test shape is not.
        if self._IN_LIKE_RE.search(masked) or self._NOT_EQUALS_RE.search(masked):
            return "org_id deve ser comparado por igualdade com sua propria org"
        if self._UNION_RE.search(masked):
            return "UNION nao permitido em consultas com dados de org"
        if self._OR_RE.search(masked):
            return "OR nao permitido junto do filtro de org (permite escapar do escopo)"
        if self._ALWAYS_TRUE_RE.search(masked):
            return "predicado sempre-verdadeiro nao permitido no filtro de org"
        if self._SUBQUERY_RE.search(masked):
            return "subquery nao permitida com filtro de org"
        return None

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
        if any(n.startswith("pg_") for n in self._referenced_tables(self._mask(q))):
            return {"error": "tabelas pg_* bloqueadas"}
        # deny credential/PII tables: no org context, so no safe way to scope rows
        if self._referenced_tables(self._mask(q)) & set(self._DENY_APP_TABLES):
            return {"error": "tabela com segredos/PII bloqueada para SQL direto; use a ferramenta do canal"}
        # org scoping: a query touching org-owned tables must filter to the
        # caller's org and no other. This is a guardrail, not a SQL parser —
        # it kills unscoped whole-table reads, the realistic exfil path.
        if self._referenced_tables(self._mask(q)) & set(self._ORG_SCOPED_TABLES):
            err = self._check_org_scope(q)
            if err:
                return {"error": err}
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
