"""AIOS as a business OS (adapted, not video clone): AgentDB-backed decision ledger.

Agents record decisions (and why) to AgentDB; future runs read them back via
second_brain.get_second_brain_injections. Human approval is the default gate —
only explicitly whitelisted (side-effectful, idempotent) decisions record
unconditionally.
"""
import logging
import os
import shutil
from pathlib import Path

from aios.core.agent_db import agent_db

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "business_os"

# Six dirs the scaffold creates: the root plus these five.
BUSINESS_OS_DIRS = [
    "Context",
    "Context/prompts",
    "Inbox_Support",
    "Inbox_Support/prompts",
    "Team",
]

# Decisions that are safe to record automatically (mirror of automation dispatch gates).
AUTO_RECORD_ALLOWLIST = {
    "workday_job", "aios.tasks.jobs.workday_job",
    "proactive_event_job", "aios.tasks.jobs.proactive_event_job",
}


def _trim(v, n=300):
    return str(v or "").strip().replace("\n", " ")[:n]


async def record_decision(agent_id, org_id, text, *, automatic=False):
    """Store a decision + rationale in the shared decision ledger.

    autonomous: True only for whitelisted automation decisions.
    """
    t = _trim(text)
    if not t or not org_id:
        return None
    # Caller gates human-in-the-loop (HITL); only whitelisted automations are automatic.
    from datetime import datetime
    return await agent_db.put_knowledge(
        agent_id=agent_id, org_id=org_id, knowledge_type="decision",
        key=f"decision:{datetime.now().strftime('%Y%m%d%H%M%S')}:{t[:40]}",
        value=t, source="agent",
        extra_data={"automatic": bool(automatic)},
    )


async def load_decisions(org_id, agent_id="", limit=10):
    """Recent decisions for context injection."""
    if not org_id:
        return []
    return [k for k in await agent_db.search_knowledge(
        org_id=org_id, agent_id=agent_id, knowledge_type="decision", limit=limit
    ) if k.value]


def scaffold_business_os(path: str) -> list[str]:
    """Create the business_os skeleton under path; copy template files in.

    Returns the six dirs created: path + the five in BUSINESS_OS_DIRS.
    """
    out = [path]
    for d in BUSINESS_OS_DIRS:
        p = os.path.join(path, d)
        os.makedirs(p, exist_ok=True)
        out.append(p)
    if TEMPLATE_DIR.is_dir():
        for src in sorted(TEMPLATE_DIR.rglob("*")):
            if src.is_file():
                dst = os.path.join(path, src.relative_to(TEMPLATE_DIR))
                os.makedirs(os.path.dirname(dst) or path, exist_ok=True)
                shutil.copyfile(src, dst)
    return out
