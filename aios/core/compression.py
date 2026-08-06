"""Context compression — summarize oldest messages instead of dropping them.

When context exceeds token budget, compress older messages into summaries
rather than truncating. Preserves more information.
"""

import logging
from aios.core.tokenizer import count_tokens

logger = logging.getLogger(__name__)


class ContextCompressor:
    """Summarize oldest messages to fit within token budget."""

    def __init__(self, preserve_recent: int = 4, aggressiveness: float = 0.5):
        self._preserve_recent = preserve_recent
        self._aggressiveness = aggressiveness  # 0=light, 1=aggressive

    async def compress_and_fit(self, messages: list[dict], max_tokens: int,
                               reserve_tokens: int = 1000,
                               llm_provider=None) -> list[dict]:
        """Compress oldest messages to fit token budget.

        Keeps system prompt + recent messages, summarizes the rest.
        Falls back to truncation if no LLM provider.
        """
        budget = max_tokens - reserve_tokens
        if budget <= 0:
            return messages[:1] if messages else []

        total = sum(count_tokens(m.get("content", "") or "") + 4 for m in messages)
        if total <= budget:
            return messages

        # split: system | middle (compressible) | recent (keep)
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= self._preserve_recent:
            return messages  # nothing to compress

        recent = non_system[-self._preserve_recent:]
        middle = non_system[:-self._preserve_recent]

        system_tokens = sum(count_tokens(m.get("content", "") or "") + 4 for m in system_msgs)
        recent_tokens = sum(count_tokens(m.get("content", "") or "") + 4 for m in recent)
        available_for_middle = budget - system_tokens - recent_tokens

        if available_for_middle <= 0:
            # recent alone exceeds budget — truncate recent
            return system_msgs + recent[-2:]

        middle_tokens = sum(count_tokens(m.get("content", "") or "") + 4 for m in middle)
        if middle_tokens <= available_for_middle:
            return messages  # fits as-is

        # need to compress middle
        if llm_provider:
            summary = await self._summarize_messages(llm_provider, middle)
            summary_tokens = count_tokens(summary) + 4
            if summary_tokens <= available_for_middle:
                compressed = system_msgs + [{"role": "system", "content": f"[Summary of earlier conversation]\n{summary}"}] + recent
            else:
                # summary still too long — truncate
                compressed = system_msgs + recent
        else:
            # no LLM — truncate middle to fit
            keep_tokens = available_for_middle
            kept_middle = []
            for m in middle:
                t = count_tokens(m.get("content", "") or "") + 4
                if keep_tokens - t < 0:
                    break
                keep_tokens -= t
                kept_middle.append(m)
            compressed = system_msgs + kept_middle + recent

        dropped = len(messages) - len(compressed)
        if dropped > 0:
            logger.debug("Compressed %d messages (%d → %d) to fit budget %d",
                         dropped, len(messages), len(compressed), max_tokens)
        return compressed

    async def _summarize_messages(self, llm_provider, messages: list[dict]) -> str:
        """Use LLM to summarize a block of messages."""
        text_parts = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")[:500]
            text_parts.append(f"{role}: {content}")
        conversation_text = "\n".join(text_parts)

        try:
            response = await llm_provider.chat(
                messages=[
                    {"role": "system", "content": "Summarize this conversation segment concisely. Keep key facts, decisions, and context. Max 300 words."},
                    {"role": "user", "content": conversation_text},
                ],
                model="openai/gpt-4o-mini",
                max_tokens=400,
            )
            return response.get("content", "") or conversation_text[:500]
        except Exception:
            logger.exception("LLM compression failed, falling back to truncation")
            return conversation_text[:500]


# Global instance
compressor = ContextCompressor()
