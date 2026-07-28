"""Convex backend — calls Convex functions via Python SDK.

Requires AIOS_CONVEX_URL and AIOS_CONVEX_ADMIN_KEY env vars.
Convex side has tables.ts defining get/list/count/create/update/delete
functions that accept a `table` param to determine which table to act on.

Calls:
  tables:get({table, id})
  tables:list({table, filters})
  tables:count({table, filters})
  tables:create({table, data})
  tables:update({table, id, data})
  tables:delete({table, id})
"""

import logging
from typing import Any

from aios.db.backend import DatabaseBackend

logger = logging.getLogger(__name__)

_MODEL_MAP = {
    "Organization": "organizations",
    "User": "users",
    "Agent": "agents",
    "AgentInstance": "agent_instances",
    "Team": "teams",
    "Conversation": "conversations",
    "Message": "messages",
    "ChannelConnection": "channel_connections",
    "Artifact": "artifacts",
    "Tool": "tools",
    "Memory": "memories",
    "UsageRecord": "usage_records",
    "RemoteInstance": "remote_instances",
    "Invitation": "invitations",
    "AuditLog": "audit_logs",
    "OAuthAccount": "oauth_accounts",
}


def _table(model: type) -> str:
    return _MODEL_MAP.get(model.__name__, model.__name__.lower())


def _obj_to_dict(obj) -> dict:
    """Convert SQLAlchemy model instance to plain dict for Convex."""
    if hasattr(obj, "__table__"):
        cols = obj.__table__.columns.keys()
        d = {}
        for c in cols:
            val = getattr(obj, c, None)
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            d[c] = val
        return d
    return dict(obj)


class ConvexBackend(DatabaseBackend):
    """Calls Convex functions via convex Python client.

    Each method maps to a tables.ts function with a `table` param.
    """

    def __init__(self, convex_url: str = "", admin_key: str = ""):
        self._url = convex_url
        self._admin_key = admin_key
        self._client = None

    async def _get_client(self):
        if self._client is None:
            try:
                from convex import ConvexClient
            except ImportError:
                raise RuntimeError("Convex client not installed. Run: pip install convex")
            self._client = ConvexClient(self._url)
            if self._admin_key:
                self._client.set_admin_auth_header(self._admin_key)
            logger.info("Convex client connected to %s", self._url)
        return self._client

    async def get(self, model: type, ident: Any) -> Any | None:
        client = await self._get_client()
        try:
            return await client.query("tables:get", {"table": _table(model), "id": str(ident)})
        except Exception as e:
            logger.warning("Convex get %s failed: %s", _table(model), e)
            return None

    async def execute(self, stmt) -> "ConvexResult":
        """Execute a select statement — maps to tables:list.

        Returns ConvexResult mimicking SQLAlchemy Result interface.
        """
        client = await self._get_client()
        table = _stmt_to_table(stmt)
        filters = _stmt_to_filters(stmt)
        try:
            data = await client.query("tables:list", {"table": table, "filters": filters})
            return ConvexResult(data)
        except Exception as e:
            logger.warning("Convex execute %s failed: %s", table, e)
            return ConvexResult([])

    def add(self, obj) -> None:
        if not hasattr(self, "_pending_adds"):
            self._pending_adds = []
        self._pending_adds.append(obj)

    async def commit(self) -> None:
        if not hasattr(self, "_pending_adds") or not self._pending_adds:
            return
        client = await self._get_client()
        pending = list(self._pending_adds)
        self._pending_adds.clear()
        for obj in pending:
            table = _table(type(obj))
            data = _obj_to_dict(obj)
            try:
                await client.mutation("tables:create", {"table": table, "data": data})
            except Exception as e:
                logger.warning("Convex create %s failed: %s", table, e)

    async def delete(self, obj) -> None:
        client = await self._get_client()
        table = _table(type(obj))
        obj_id = getattr(obj, "id", None) or getattr(obj, "_id", None)
        if obj_id:
            try:
                await client.mutation("tables:delete", {"table": table, "id": obj_id})
            except Exception as e:
                logger.warning("Convex delete %s failed: %s", table, e)

    async def flush(self) -> None:
        pass  # No-op for Convex

    async def refresh(self, obj) -> None:
        client = await self._get_client()
        table = _table(type(obj))
        obj_id = getattr(obj, "id", None) or getattr(obj, "_id", None)
        if obj_id:
            try:
                fresh = await client.query("tables:get", {"table": table, "id": obj_id})
                if fresh and hasattr(obj, "__table__"):
                    for key, val in fresh.items():
                        if hasattr(obj, key):
                            setattr(obj, key, val)
            except Exception as e:
                logger.warning("Convex refresh %s failed: %s", table, e)

    async def close(self) -> None:
        self._client = None

    async def health(self) -> bool:
        try:
            client = await self._get_client()
            await client.query("health:check", {})
            return True
        except Exception as e:
            logger.warning("Convex health check failed: %s", e)
            return False


def _stmt_to_table(stmt) -> str:
    """Extract table name from a SQLAlchemy select statement."""
    try:
        return stmt.froms[0].name
    except (AttributeError, IndexError, TypeError):
        return "unknown"


def _stmt_to_filters(stmt) -> dict:
    """Extract simple WHERE filters from a select statement."""
    try:
        filters = {}
        for pred in stmt.whereclause.clauses:
            filters[str(pred.left.name)] = pred.right.value
        return filters
    except (AttributeError, TypeError):
        return {}


class ConvexResult:
    """Mimics SQLAlchemy Result for Convex query responses."""

    def __init__(self, data: list | dict | None):
        self._data = data or []

    def scalar(self):
        if isinstance(self._data, list) and len(self._data) == 1:
            return self._data[0]
        return None

    def scalars(self):
        return ConvexScalars(self._data)

    def all(self):
        return self._data if isinstance(self._data, list) else [self._data]

    def first(self):
        if isinstance(self._data, list) and self._data:
            return self._data[0]
        return None


class ConvexScalars:
    """Mimics RowReturningResult.scalars() for Convex."""

    def __init__(self, data):
        self._data = data if isinstance(data, list) else [data]

    def all(self):
        return self._data
