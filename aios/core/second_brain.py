"""Second brain (AIOS-native, fits AgentDB instead of Alan Nicolas' video flow).

- Retrieval: AgentDB reflections/learnings/knowledge injected as context — best-effort.
- Consolidation: autonomous reflections -> AgentDB knowledge + success learnings.
"""
import logging

from aios.core.agent_db import agent_db

logger = logging.getLogger(__name__)


def _trim(value, n=400):
    return str(value or "").strip().replace("\n", " ")[:n]


async def get_second_brain_injections(agent_id, org_id, query, top_k=3):
    """Inject recent AgentDB reflections + learnings + knowledge. Best-effort."""
    lines = []
    if not org_id:
        return []
    try:
        for r in await agent_db.list_reflections(org_id=org_id, agent_id=agent_id, limit=5):
            insight = _trim(r.key_insight or r.what_went_well)
            if insight:
                lines.append(f"- Reflexão do histórico: {insight}")
    except Exception:
        logger.debug("second_brain: reflection retrieval failed", exc_info=True)
    try:
        for k in await agent_db.search_knowledge(
            org_id=org_id, agent_id=agent_id, knowledge_type="decision", limit=5
        ):
            lines.append(f"- Decisão registrada: {_trim(k.value)}")
    except Exception:
        logger.debug("second_brain: decision retrieval failed", exc_info=True)
    try:
        for l in await agent_db.list_learnings(org_id=org_id, agent_id=agent_id, limit=5):
            if l.success:
                t = _trim(l.outcome or l.action_taken)
                if t:
                    lines.append(f"- Learning do histórico (sucesso): {t}")
    except Exception:
        logger.debug("second_brain: learning retrieval failed", exc_info=True)
    if not lines:
        return []
    return [{"role": "system",
             "content": "=== Second Brain (AgentDB) ===\n" + "\n".join(lines[:top_k])}]


async def consolidate_reflection(agent_id, org_id, conversation_id, reflections):
    """Write reflections to AgentDB: knowledge fact + success learning (best-effort)."""
    if not org_id:
        return
    ref = _trim(" | ".join(_trim(x, 200) for x in (reflections or []) if _trim(x, 200)), 400)
    if not ref:
        return
    try:
        existing = await agent_db.search_knowledge(
            org_id=org_id, agent_id=agent_id, q=ref, limit=5
        )
        if not any((e.extra_data or {}).get("reflection_id") for e in existing):
            from datetime import datetime

            await agent_db.put_knowledge(
                agent_id=agent_id, org_id=org_id, knowledge_type="correction",
                key=f"reflection:{datetime.now().strftime('%Y%m%d')}:{ref[:60]}",
                value=ref, source="reflection",
                extra_data={"conversation_id": conversation_id},
            )
    except Exception:
        logger.debug("second_brain: knowledge write failed", exc_info=True)
    try:
        from aios.core.agent_db import _pattern_sig
        from aios.db.backend import db_session
        from aios.db.models import AgentLearning
        from sqlalchemy import select, func

        sig = _pattern_sig(_trim(ref, 100), _trim(ref, 200))
        async with db_session() as db:
            dup = (await db.execute(
                select(func.count(AgentLearning.id)).where(
                    AgentLearning.pattern_signature == sig,
                    AgentLearning.org_id == org_id,
                    AgentLearning.agent_id == agent_id,
                )
            )).scalar() or 0
        if dup == 0:
            await agent_db.record_learning(
                agent_id=agent_id, org_id=org_id, learning_type="success_pattern",
                trigger_context=_trim(ref, 300), action_taken=_trim(ref, 300),
                outcome=_trim(ref, 300), success=True,
                extra_data={"conversation_id": conversation_id},
            )
    except Exception:
        logger.debug("second_brain: learning write failed", exc_info=True)
