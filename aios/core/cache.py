"""Simple LRU response cache for LLM calls.

Cache key = sha256(scope + messages_json + model + temperature + tools).
Bypass with X-AIOS-Bypass-Cache: true header.

`scope` is the org id. Without it the key was the same for every tenant, so
org B's `sql_query` result was served to org A for the identical SQL string.
The caches are process-global, so this is the only thing keeping them
per-tenant.
"""

import hashlib
import json
import time
from collections import OrderedDict

_MAX_SIZE = 500
_DEFAULT_TTL = 3600  # 1 hour
_TOOL_CACHE_TTL = 300  # 5 min for tool results


class ResponseCache:
    """LRU cache with TTL for LLM responses."""

    def __init__(self, max_size: int = _MAX_SIZE, default_ttl: int = _DEFAULT_TTL):
        self._data: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl

    def _key(self, messages: list[dict], model: str, temperature: float,
              tools: list | None = None, scope: str = "") -> str:
        raw = json.dumps({"o": scope, "m": messages, "mo": model, "t": temperature, "tl": tools}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, messages: list[dict], model: str, temperature: float,
            tools: list | None = None, scope: str = "") -> dict | None:
        k = self._key(messages, model, temperature, tools, scope)
        if k not in self._data:
            return None
        ts, val = self._data[k]
        if time.time() - ts > self._default_ttl:
            del self._data[k]
            return None
        # LRU: move to end
        self._data.move_to_end(k)
        return val

    def set(self, messages: list[dict], model: str, temperature: float, value: dict,
            tools: list | None = None, scope: str = "") -> None:
        k = self._key(messages, model, temperature, tools, scope)
        self._data[k] = (time.time(), value)
        self._data.move_to_end(k)
        if len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def stats(self) -> dict:
        return {"size": len(self._data), "max_size": self._max_size, "ttl": self._default_ttl}


class ToolResultCache:
    """Time-based cache for tool execution results.

    Keyed by (org_id, tool_name, arg_hash). TTL shorter than response cache
    since tool results (web searches, etc.) go stale faster.

    The org is part of the key, not decoration: `sql_query` and `read_file`
    return org-scoped rows, and two tenants issuing the same query got each
    other's rows out of this process-global cache.
    """

    def __init__(self, max_size: int = 200, default_ttl: int = _TOOL_CACHE_TTL):
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl

    def _key(self, name: str, args_json: str, scope: str = "") -> str:
        return hashlib.sha256(f"{scope}:{name}:{args_json}".encode()).hexdigest()

    def get(self, name: str, args_json: str, scope: str = "") -> str | None:
        k = self._key(name, args_json, scope)
        if k not in self._data:
            return None
        ts, val = self._data[k]
        if time.time() - ts > self._default_ttl:
            del self._data[k]
            return None
        self._data.move_to_end(k)
        return val

    def set(self, name: str, args_json: str, result: str, scope: str = "") -> None:
        k = self._key(name, args_json, scope)
        self._data[k] = (time.time(), result)
        self._data.move_to_end(k)
        if len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


# ponytail: global caches, partitioned by org id in the key (see module
# docstring). Separate per-org caches would be the next step up.
cache = ResponseCache()
tool_cache = ToolResultCache()
