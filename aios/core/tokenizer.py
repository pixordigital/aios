"""Token counting for context budget management.

Tries tiktoken first, falls back to char/4 estimate.
"""

import logging
import re

logger = logging.getLogger(__name__)

_TIKTOKEN = None


def _load_tiktoken():
    global _TIKTOKEN
    if _TIKTOKEN is None:
        try:
            import tiktoken
            _TIKTOKEN = tiktoken.get_encoding("cl100k_base")
            logger.info("Loaded tiktoken for token counting")
        except ImportError:
            _TIKTOKEN = False
    return _TIKTOKEN if _TIKTOKEN is not False else None


def count_tokens(text: str) -> int:
    """Count tokens in text. Accurate if tiktoken installed, estimate otherwise."""
    enc = _load_tiktoken()
    if enc:
        return len(enc.encode(text))
    # rough: ~4 chars per token for English
    return max(1, len(text) // 4)


def count_message_tokens(msg: dict) -> int:
    """Count tokens in a single message dict, including role overhead."""
    overhead = 4  # role + formatting
    content = msg.get("content", "") or ""
    return count_tokens(content) + overhead


def truncate_context(
    messages: list[dict],
    max_tokens: int,
    reserve_tokens: int = 1000,
) -> list[dict]:
    """Truncate message list to fit within max_tokens budget.

    Keeps system prompt and recent messages, drops oldest first.
    Reserves `reserve_tokens` for the response.
    """
    budget = max_tokens - reserve_tokens
    if budget <= 0:
        return messages[:1] if messages else []  # keep system prompt only

    # Count from most recent backwards
    total = 0
    # Always keep system prompt (index 0 if it's system)
    keep_idx = 0
    for i in range(len(messages) - 1, -1, -1):
        tokens = count_message_tokens(messages[i])
        if total + tokens > budget:
            keep_idx = i + 1
            break
        total += tokens
        keep_idx = i

    truncated = messages[keep_idx:]
    dropped = len(messages) - len(truncated)
    if dropped > 0:
        logger.debug("Truncated %d messages to fit budget %d", dropped, max_tokens)

    return truncated
