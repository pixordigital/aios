"""Memory Layer — captura insight pós closed_won/lost (Synkra Epic 7)."""

import logging
from aios.qa.sdr_qa import capture_insight, score_conversation

logger = logging.getLogger(__name__)

async def capture_deal_insight(org_id: str, deal_id: str, new_stage: str, conversation: list[dict] | None = None):
    """Salva insight + score QA como Memory long_term."""
    try:
        from aios.db.engine import async_session
        from sqlalchemy import select
        from aios.db.models import Memory, Agent
        conv = conversation or []
        insight = capture_insight(new_stage, conv)
        score = score_conversation(conv, rag_hits=1 if any("fonte" in str(c).lower() for c in conv) else 0)
        async with async_session() as s:
            ag = (await s.execute(select(Agent).where(Agent.org_id == org_id).limit(1))).scalars().first()
            agent_id = ag.id if ag else "00000000-0000-0000-0000-000000000000"
            m = Memory(
                agent_id=agent_id,
                org_id=org_id,
                type="long_term",
                content=f"{insight} | QA {score['total']}/10",
                extra_data={"source": f"deal:{deal_id}", "stage": new_stage, "qa": score, "kind": "insight"},
            )
            s.add(m)
            await s.commit()
            logger.info("insight captured %s %s QA %s/10", deal_id, new_stage, score["total"])
            return {"ok": True, "qa": score}
    except Exception as e:
        logger.warning("capture insight failed %s", e)
        return {"ok": False, "error": str(e)[:300]}
