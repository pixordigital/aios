import logging

logger = logging.getLogger(__name__)


async def check_autoscale(org_id: str) -> dict:
    try:
        from sqlalchemy import select

        from aios.db.engine import async_session
        from aios.db.models import AgentMetric

        async with async_session() as sess:
            rows = (
                await sess.execute(select(AgentMetric).where(AgentMetric.org_id == org_id).order_by(AgentMetric.hour.desc()).limit(20))
            ).scalars().all()
            if not rows:
                return {"scale": "none", "reason": "no metrics"}
            avg_lat = sum(r.avg_response_ms for r in rows) / len(rows)
            total_err = sum(r.errors for r in rows)
            total_msg = sum(r.messages for r in rows) or 1
            err_rate = total_err / total_msg
            if avg_lat > 3000 or err_rate > 0.05:
                logger.warning("Autoscale UP org %s lat=%.0f err=%.1f%%", org_id, avg_lat, err_rate * 100)
                return {"scale": "up", "avg_latency": avg_lat, "error_rate": err_rate}
            if avg_lat < 800 and err_rate < 0.01:
                return {"scale": "down", "avg_latency": avg_lat, "error_rate": err_rate}
            return {"scale": "stable", "avg_latency": avg_lat, "error_rate": err_rate}
    except Exception as e:
        logger.debug("autoscale check failed: %s", e)
        return {"scale": "unknown", "error": str(e)}
