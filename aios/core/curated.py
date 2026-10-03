"""Agent-curated memory blocks (MEMORY.md / USER.md semantics).

Two flat, capacity-bounded entry lists injected frozen at run start:

* `memory` — the agent's own notes: environment facts, conventions, lessons.
  Stored on the agent row.
* `user` — the agent's model of the human it serves: preferences, style.
  Stored on the org row (one operator profile, not one copy per agent that
  would silently diverge).

The agent curates both through the `memory` tool (add/replace/remove with
unique-substring matching). When a write would exceed capacity the tool
returns an error carrying the current entries, so the agent consolidates
with replace/remove in the same turn instead of the write silently dropping —
the Hermes full-memory behavior this mirrors.

Entries are stored as JSON lists (not §-delimited text): same semantics,
no delimiter parsing. Every entry passes the store scan on the way in.
"""

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

MEMORY_CHAR_LIMIT = 2200  # ~800 tokens
USER_CHAR_LIMIT = 1375  # ~500 tokens

_LIMITS = {"memory": MEMORY_CHAR_LIMIT, "user": USER_CHAR_LIMIT}
_TITLES = {"memory": "CURATED MEMORY (agent notes)", "user": "USER PROFILE"}


def _used(entries: list[str]) -> int:
    return sum(len(e) for e in (entries or []))


def usage(entries: list[str], kind: str) -> tuple[int, int]:
    """(used_chars, limit) for a block."""
    limit = _LIMITS[kind]
    return _used(entries), limit


def _locate(entries: list[str], needle: str) -> int:
    """Index of the unique entry containing needle, else raise LookupError."""
    hits = [i for i, e in enumerate(entries) if needle in e]
    if not hits:
        raise LookupError(f"no entry contains {needle!r}")
    if len(hits) > 1:
        raise LookupError(
            f"{needle!r} matches {len(hits)} entries — be more specific"
        )
    return hits[0]


def _capacity_error(entries: list[str], kind: str, extra: int) -> dict:
    limit = _LIMITS[kind]
    return {
        "error": (
            f"{kind} block at {_used(entries)}/{limit} chars; adding {extra} chars "
            f"would exceed the limit. Consolidate now: use replace to merge "
            f"overlapping entries into shorter ones or remove stale ones, then "
            f"retry — all in this turn."
        ),
        "current_entries": list(entries),
        "usage": f"{_used(entries)}/{limit}",
    }


def add_entry(entries: list[str], kind: str, content: str) -> tuple[list[str], dict | None]:
    """Append one entry. Returns (new_entries, None) or (entries, error)."""
    from aios.core.content_scan import check_store_text

    content = (content or "").strip()
    if not content:
        return list(entries), {"error": "content is empty — nothing to store"}
    scanned = check_store_text(content, source=f"curated:{kind}")
    if scanned is None:
        return list(entries), {"error": "content rejected by store scan"}
    if any(scanned == e for e in entries):
        return list(entries), {"error": "duplicate — this entry already exists"}
    if _used(entries) + len(scanned) > _LIMITS[kind]:
        return list(entries), _capacity_error(entries, kind, len(scanned))
    return [*entries, scanned], None


def replace_entry(entries: list[str], kind: str, old_text: str, content: str) -> tuple[list[str], dict | None]:
    """Replace the whole uniquely-matched entry. old_text only locates it."""
    from aios.core.content_scan import check_store_text

    try:
        idx = _locate(list(entries), old_text)
    except LookupError as e:
        return list(entries), {"error": str(e), "current_entries": list(entries)}
    content = (content or "").strip()
    if not content:
        return list(entries), {"error": "replacement content is empty"}
    scanned = check_store_text(content, source=f"curated:{kind}")
    if scanned is None:
        return list(entries), {"error": "content rejected by store scan"}
    new_entries = list(entries)
    new_entries[idx] = scanned
    if _used(new_entries) > _LIMITS[kind]:
        return list(entries), _capacity_error(entries, kind, len(scanned))
    return new_entries, None


def remove_entry(entries: list[str], old_text: str) -> tuple[list[str], dict | None]:
    """Remove the uniquely-matched entry."""
    try:
        idx = _locate(list(entries), old_text)
    except LookupError as e:
        return list(entries), {"error": str(e), "current_entries": list(entries)}
    return [e for i, e in enumerate(entries) if i != idx], None


def format_block(kind: str, entries: list[str]) -> str:
    """Frozen block for the system prompt, with a capacity header so the agent
    sees the budget. Empty blocks render as "" and are omitted by the caller.
    Over 80% the footer tells the agent to consolidate before adding."""
    entries = entries or []
    if not entries:
        return ""
    used, limit = usage(entries, kind)
    pct = int(100 * used / limit) if limit else 0
    lines = [f"[{_TITLES[kind]} | {pct}% used ({used}/{limit} chars)]"]
    lines.extend(f"- {e}" for e in entries)
    if pct >= 80:
        lines.append(
            "(over 80% full — consolidate with replace/remove before adding)"
        )
    return "\n".join(lines)


# ─── storage (agent row: memory, org row: user) ───────────────────────────

_MEMORY_KEY = "curated_memory"
_USER_KEY = "curated_user"


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def load_blocks(agent_id: str, org_id: str) -> dict[str, list[str]]:
    """Read both blocks. Never raises (hot path) — failures read as empty."""
    out = {"memory": [], "user": []}
    try:
        from aios.db.backend import db_session
        from aios.db.models import Agent, Organization

        async with db_session() as db:
            if agent_id:
                agent = await db.get(Agent, agent_id)
                extra = getattr(agent, "extra_data", None) or {}
                out["memory"] = list((extra.get(_MEMORY_KEY) or {}).get("entries", []))
            if org_id:
                org = await db.get(Organization, org_id)
                extra = getattr(org, "extra_data", None) or {}
                out["user"] = list((extra.get(_USER_KEY) or {}).get("entries", []))
    except Exception:
        logger.debug("curated load failed", exc_info=True)
    return out


async def save_block(kind: str, entries: list[str], agent_id: str, org_id: str) -> bool:
    """Persist one block (reassigns extra_data so the JSON column dirties).
    Returns False instead of raising — the caller reports it as a tool error."""
    try:
        from aios.db.backend import db_session
        from aios.db.models import Agent, Organization

        async with db_session() as db:
            if kind == "memory":
                agent = await db.get(Agent, agent_id)
                if agent is None:
                    return False
                extra = dict(getattr(agent, "extra_data", None) or {})
                extra[_MEMORY_KEY] = {"entries": list(entries), "updated_at": _now()}
                agent.extra_data = extra
            else:
                org = await db.get(Organization, org_id)
                if org is None:
                    return False
                extra = dict(getattr(org, "extra_data", None) or {})
                extra[_USER_KEY] = {"entries": list(entries), "updated_at": _now()}
                org.extra_data = extra
            await db.commit()
            return True
    except Exception:
        logger.warning("curated save failed for %s", kind, exc_info=True)
        return False
