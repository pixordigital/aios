"""Simple LRU response cache for LLM calls.

Cache key = sha256(messages_json + model + temperature + tools).
Bypass with X-AIOS-Bypass-Cache: true header.
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

    def _key(self, messages: list[dict], model: str, temperature: float, tools: list | None = None) -> str:
        raw = json.dumps({"m": messages, "mo": model, "t": temperature, "tl": tools}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, messages: list[dict], model: str, temperature: float, tools: list | None = None) -> dict | None:
        k = self._key(messages, model, temperature, tools)
        if k not in self._data:
            return None
        ts, val = self._data[k]
        if time.time() - ts > self._default_ttl:
            del self._data[k]
            return None
        # LRU: move to end
        self._data.move_to_end(k)
        return val

    def set(self, messages: list[dict], model: str, temperature: float, value: dict, tools: list | None = None) -> None:
        k = self._key(messages, model, temperature, tools)
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

    Keyed by (tool_name, arg_hash). TTL shorter than response cache
    since tool results (web searches, etc.) go stale faster.
    """

    def __init__(self, max_size: int = 200, default_ttl: int = _TOOL_CACHE_TTL):
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl

    def _key(self, name: str, args_json: str) -> str:
        return hashlib.sha256(f"{name}:{args_json}".encode()).hexdigest()

    def get(self, name: str, args_json: str) -> str | None:
        k = self._key(name, args_json)
        if k not in self._data:
            return None
        ts, val = self._data[k]
        if time.time() - ts > self._default_ttl:
            del self._data[k]
            return None
        self._data.move_to_end(k)
        return val

    def set(self, name: str, args_json: str, result: str) -> None:
        k = self._key(name, args_json)
        self._data[k] = (time.time(), result)
        self._data.move_to_end(k)
        if len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


# ponytail: global caches. Per-agent or per-org caches when contention matters.
cache = ResponseCache()
tool_cache = ToolResultCache()
