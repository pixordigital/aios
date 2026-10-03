"""Store-time scan for memory entries and skills.

Anything persisted here is re-injected into future system prompts (memory
injections, skill context), so a stored prompt-injection outlives the turn it
arrived in and fires on every later run. Scanning at the store — not at
render — closes that persistence vector once for all readers.

Two layers, deliberately different severities:

* invisible unicode is *stripped*, always: zero-width chars, bidi overrides
  and lookalike tricks have no legitimate use in a memory entry or skill and
  stripping them never breaks real content;
* instruction-override patterns *reject* the write: the reply still goes out,
  only the persistence is refused, so a false positive costs a missing memory,
  never a broken conversation.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Zero-width / invisible / bidi-override codepoints. Stripped, not blocked.
_INVISIBLE_RE = re.compile(
    "[\u200b\u200c\u200d\u2060\ufeff\u180e"
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
    "\u00ad\U000e0000-\U000e0fff]",
)

# Instruction-override shapes: imperative addressed at the model/its prompt,
# not at a task. Kept short on purpose — pattern lists rot, and every entry
# must be precise enough that a SOC agent storing "attacker said X" as an
# observation is not the common case. Matched case-insensitively.
_INJECTION_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions",
        r"disregard\s+(all\s+)?(previous|prior|above|your)\s+(instructions|prompt|rules|system)",
        r"forget\s+(everything|all)\s+(you were told|above|before)",
        r"you are now\s+(a|an|in)\s+\w+",  # role hijack opener
        r"system\s*:\s*new instructions",
        r"reveal\s+(your\s+)?(system|secret|hidden)\s+(prompt|instructions|key)",
        r"exfiltrat\w*\s+(to|via|through)\s+\S+",
        r"send\s+(all\s+)?(secrets|credentials|api[_-]?keys?|passwords)\s+to\s+\S+",
    )
]


def scrub_invisible(text: str) -> str:
    """Remove zero-width/bidi-override chars. Also folds compatibility lookalikes
    via NFKC so full-width "ｉｇｎｏｒｅ" cannot dodge the patterns below."""
    if not text:
        return text
    cleaned = _INVISIBLE_RE.sub("", text)
    return unicodedata.normalize("NFKC", cleaned)


def find_injection(text: str) -> str | None:
    """Return the matched pattern source, or None if clean.

    Scrubs first: without this, calling find_injection directly on raw text
    (instead of through check_store_text) let full-width lookalikes sail
    past the patterns — the exact bypass the scrub exists to close.
    """
    cleaned = scrub_invisible(text or "")
    if not cleaned:
        return None
    for rx in _INJECTION_RES:
        if rx.search(cleaned):
            return rx.pattern
    if _has_mixed_script_token(cleaned):
        return "mixed-script homoglyph"
    return None


# Scripts with real Latin lookalikes (Cyrillic а/е/і/о, Greek ο/ρ, ...).
# CJK is deliberately excluded: it has no Latin lookalikes, and CJK text uses
# no spaces, so whole sentences would read as one "token" and any Latin brand
# name inside (e.g. "用WhatsApp联系") would false-positive.
_LOOKALIKE_SCRIPTS = frozenset({"CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE"})


def _char_script(ch: str) -> str | None:
    """Letter script of one char via its Unicode name, else None.

    Only categories starting with L count: digits, punctuation and marks are
    script-neutral (a hyphen or "R$ 42" must never trip the rule).
    """
    if not unicodedata.category(ch).startswith("L"):
        return None
    return unicodedata.name(ch, "").split(" ", 1)[0] or None


def _has_mixed_script_token(text: str) -> bool:
    """True if any whitespace-token mixes Latin with a lookalike script.

    Single-script tokens pass untouched — a Russian sentence or a Chinese
    paragraph is legitimate stored content. Only the *mix inside one token*
    is the attack shape ("іgnore" = Cyrillic і + Latin gnore).
    """
    for token in text.split():
        scripts = {_char_script(ch) for ch in token}
        scripts.discard(None)
        if "LATIN" in scripts and scripts & _LOOKALIKE_SCRIPTS:
            return True
    return False


def check_store_text(text: str | None, *, source: str) -> str | None:
    """Scrub + gate one piece of stored content.

    Returns the scrubbed text, or None when the write must be refused.
    Never raises: a scanner that throws would fail open or break replies.
    """
    try:
        cleaned = scrub_invisible(text or "")
        hit = find_injection(cleaned)
        if hit:
            logger.warning("store rejected (%s): matched %s", source, hit)
            return None
        return cleaned
    except Exception:
        logger.exception("content scan failed for %s", source)
        return text
