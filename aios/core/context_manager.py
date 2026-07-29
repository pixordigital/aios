"""Context manager — handle context caching, switching, and budget enforcement.

Separate from memory. Responsibilities:
- Cache assembled context blocks per (conversation, agent)
- Context switching when scheduler preempts agents
- Token budget enforcement (moved from tokenizer.py)
- Smart eviction when cache fills

ponytail: in-memory LRU cache. External cache (Redis) when multi-process.
"""

import logging
from collections import OrderedDict
from dataclasses import dataclass

from aios.core.hooks import HookContext, HookPoint, hooks
from aios.core.tokenizer import count_tokens

logger = logging.getLogger(__name__)

_MAX_CACHED_CONTEXTS = 100


@dataclass
class SavedContext:
    """Serialised context state — enough to resume without rebuilding."""
    conversation_id: str
    agent_id: str
    message_block: list[dict]  # the non-system messages
    token_count: int = 0
    message_count: int = 0
    # scheduler preemption metadata
    preempted_at_step: int = 0
    partial_response: str = ""


class ContextManager:
    """Manage context cache, switching, and token budgets."""

    def __init__(self, max_cached: int = _MAX_CACHED_CONTEXTS):
        self._cache: OrderedDict[str, SavedContext] = OrderedDict()
        self._max_cached = max_cached
        # active context per conversation (avoids rebuilding)
        self._active: dict[str, SavedContext] = {}

    # ─── Cache ───

    def cache_key(self, conv_id: str, agent_id: str) -> str:
        return f"{conv_id}:{agent_id}"

    def save(self, conv_id: str, agent_id: str, messages: list[dict]) -> SavedContext:
        """Save current context state into cache."""
        # separate system from non-system
        non_system = [m for m in messages if m.get("role") != "system"]
        sc = SavedContext(
            conversation_id=conv_id,
            agent_id=agent_id,
            message_block=list(non_system),
            token_count=sum(count_tokens(m.get("content", "") or "") for m in non_system),
            message_count=len(non_system),
        )
        key = self.cache_key(conv_id, agent_id)
        self._cache[key] = sc
        self._cache.move_to_end(key)
        self._evict_if_needed()
        self._active[key] = sc
        return sc

    def load(self, conv_id: str, agent_id: str) -> SavedContext | None:
        """Load cached context if available."""
        key = self.cache_key(conv_id, agent_id)
        sc = self._cache.get(key)
        if sc:
            self._cache.move_to_end(key)
            self._active[key] = sc
        return sc

    def drop(self, conv_id: str, agent_id: str) -> None:
        key = self.cache_key(conv_id, agent_id)
        self._cache.pop(key, None)
        self._active.pop(key, None)

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self._max_cached:
            self._cache.popitem(last=False)

    # ─── Context Switching (for scheduler preemption) ───

    def save_for_switch(self, conv_id: str, agent_id: str, messages: list[dict],
                        step: int = 0, partial: str = "") -> None:
        """Save context when preempting an agent. Preserves partial progress."""
        sc = self.save(conv_id, agent_id, messages)
        sc.preempted_at_step = step
        sc.partial_response = partial
        _fire_hook("context_save", agent_id, conv_id)

    def restore_after_switch(self, conv_id: str, agent_id: str) -> SavedContext | None:
        """Restore context after being preempted."""
        sc = self.load(conv_id, agent_id)
        if sc:
            _fire_hook("context_restore", agent_id, conv_id)
        return sc

    # ─── Token Budget ───

    def enforce_budget(self, messages: list[dict], max_tokens: int,
                       reserve_tokens: int = 1000) -> list[dict]:
        """Truncate message list to fit token budget.

        Keeps system prompt, drops oldest non-system messages first.
        Reserves tokens for response generation.
        """
        budget = max_tokens - reserve_tokens
        if budget <= 0:
            return messages[:1] if messages else []

        total = 0
        keep_idx = 0
        for i in range(len(messages) - 1, -1, -1):
            t = count_tokens(messages[i].get("content", "") or "") + 4
            if total + t > budget:
                keep_idx = i + 1
                break
            total += t
            keep_idx = i

        truncated = messages[keep_idx:]
        dropped = len(messages) - len(truncated)
        if dropped > 0:
            logger.debug("Truncated %d messages to fit budget %d", dropped, max_tokens)

        return truncated

    def stats(self) -> dict:
        return {
            "cached_contexts": len(self._cache),
            "max_cached": self._max_cached,
            "active_contexts": len(self._active),
        }


def _fire_hook(event: str, agent_id: str, conv_id: str):
    """Fire hook with a minimal context."""
    try:
        hc = HookContext()
        hc.agent_id = agent_id
        hc.conversation_id = conv_id
        hc.data["event"] = event
        if event in ("before_llm", "after_llm"):
            hooks.fire(HookPoint.AFTER_LLM_CALL, hc)
        # ponytail: few hooks for now. Expand as needed.
    except Exception:
        logger.exception("Hook fire failed: %s / %s", agent_id, event)


# Global instance
context_manager = ContextManager()
