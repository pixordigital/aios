"""OnePersonOS — AIOS template for a true one-person business.

Scaffold: Context, Decision Log, Inbox, Work, Log dirs.
Sync: when a team brain is configured, pushes working-doc summaries into
AgentDB as team knowledge so the team sees the owner's one-person OS.
"""
import logging
import os

logger = logging.getLogger(__name__)

DIRS = ["Context", "Decision_Log", "Inbox", "Work", "Log"]


def scaffold_one_person_os(path: str) -> list[str]:
    """Create the five directories. Returns the dir paths created."""
    out = []
    for d in DIRS:
        p = os.path.join(path, d)
        os.makedirs(p, exist_ok=True)
        out.append(p)
    return out


async def sync_one_person_os_to_team_brain(workspace_path: str, org_id: str = "") -> int:
    """Sync Decision Log files into AgentDB knowledge (best-effort, deduped).

    Requires org_id; returns count synced.
    """
    if not org_id:
        return 0
    log_dir = os.path.join(workspace_path, "Log")
    count = 0
    if not os.path.isdir(log_dir):
        return 0
    try:
        from aios.core.agent_db import agent_db

        for fname in sorted(os.listdir(log_dir)):
            if not fname.endswith(".md") or fname.startswith("_"):
                continue
            with open(os.path.join(log_dir, fname), encoding="utf-8", errors="replace") as fh:
                text = fh.read()[:4000]
            if not text.strip():
                continue
            try:
                await agent_db.put_knowledge(
                    agent_id="", org_id=org_id, knowledge_type="procedure",
                    key=f"one_person_os:{fname}", value=text, source="ops",
                )
                count += 1
            except Exception:
                logger.debug("one_person_os sync failed: %s", fname)
    except Exception:
        logger.debug("one_person_os sync failed", exc_info=True)
    return count
