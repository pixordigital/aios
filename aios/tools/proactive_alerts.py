"""Proactive alerts — sales drop detection."""

import logging
from datetime import datetime, timedelta
from sqlalchemy import text

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY
from aios.db.engine import async_session
from aios.db.models import Organization, ChannelConnection, Memory

logger = logging.getLogger(__name__)


async def check_sales_drop(org_id: str) -> dict | None:
    """Check if sales dropped >12% yesterday vs 7-day average.

    Returns alert dict if threshold exceeded, else None.
    """
    try:
        async with async_session() as sess:
            # Check if org has proactive alerts enabled
            org = await sess.get(Organization, org_id)
            if not org or not isinstance(org.extra_data, dict):
                return None
            if not org.extra_data.get("proactive_alerts", False):
                return None

            # Check for active Evolution channel
            evo_conn = (
                await sess.execute(
                    text(
                        """
                        SELECT id FROM channel_connections
                        WHERE org_id = :org_id
                        AND channel_type = 'evolution'
                        AND is_active = true
                        LIMIT 1
                        """
                    ),
                    {"org_id": org_id},
                )
            ).scalar_one_or_none()
            if not evo_conn:
                return None

            # Query sales data: last 8 days, closed_won deals per day
            sql = """
                SELECT
                    DATE(created_at) as sale_date,
                    COALESCE(SUM(value), 0) as daily_total
                FROM crm_deals
                WHERE org_id = :org_id
                AND stage = 'closed_won'
                AND created_at >= :start_date
                GROUP BY DATE(created_at)
                ORDER BY sale_date
            """
            start_date = datetime.utcnow().date() - timedelta(days=7)
            rows = (await sess.execute(text(sql), {"org_id": org_id, "start_date": start_date})).fetchall()

            if not rows:
                return None

            # Build daily totals map
            daily_totals = {row[0]: float(row[1]) for row in rows}

            # Yesterday's date
            yesterday = datetime.utcnow().date() - timedelta(days=1)
            yesterday_total = daily_totals.get(yesterday, 0.0)

            # 7-day average (excluding yesterday if it's in the window)
            # We have 8 days of data (today-7 to today), but we want 7-day avg
            # Use the 7 days before yesterday
            seven_days_before = [daily_totals.get(yesterday - timedelta(days=i), 0.0) for i in range(1, 8)]
            avg_7d = sum(seven_days_before) / 7 if seven_days_before else 0.0

            if avg_7d == 0:
                return None

            drop_pct = ((avg_7d - yesterday_total) / avg_7d) * 100

            if drop_pct <= 12:
                return None

            alert = {
                "type": "sales_drop",
                "org_id": org_id,
                "yesterday_total": yesterday_total,
                "avg_7d": round(avg_7d, 2),
                "drop_pct": round(drop_pct, 1),
                "date": yesterday.isoformat(),
                "message": f"⚠️ Queda de vendas: {drop_pct:.1f}% (ontem: {yesterday_total:,.2f} vs média 7d: {avg_7d:,.2f})",
            }

            # Store alert in Memory for dashboard
            mem = Memory(
                org_id=org_id,
                type="alert",
                content=alert["message"],
                extra_data=alert,
            )
            sess.add(mem)
            await sess.commit()

            logger.info("Proactive alert triggered for org %s: %s", org_id, alert["message"])
            return alert

    except Exception as e:
        logger.exception("check_sales_drop failed for org %s: %s", org_id, e)
        return None


async def send_alert_via_evolution(org_id: str, alert: dict) -> bool:
    """Send alert message via active Evolution channel for org."""
    try:
        async with async_session() as sess:
            # Get active Evolution channel with config
            conn = (
                await sess.execute(
                    text(
                        """
                        SELECT id, config FROM channel_connections
                        WHERE org_id = :org_id
                        AND channel_type = 'evolution'
                        AND is_active = true
                        LIMIT 1
                        """
                    ),
                    {"org_id": org_id},
                )
            ).fetchone()
            if not conn:
                return False

            from aios.channels.evolution import EvolutionChannel
            from aios.channels.base import OutboundMessage

            channel = EvolutionChannel(connection=conn, db=sess)
            if not channel.instance or not channel.api_key:
                logger.warning("Evolution not configured for org %s", org_id)
                return False

            # Get default number from config or org
            default_number = channel._config.get("default_number") or channel._config.get("admin_number")
            if not default_number:
                logger.warning("No default_number configured for Evolution channel org %s", org_id)
                return False

            msg = OutboundMessage(text=alert["message"], extra_data={"from_number": default_number})
            result = await channel.send(msg)
            return result is not None

    except Exception as e:
        logger.exception("send_alert_via_evolution failed for org %s: %s", org_id, e)
        return False


class ProactiveAlertsTool(BaseTool):
    name = "proactive_alerts"
    description = "Verifica queda de vendas >12% e envia alerta proativo via WhatsApp (Evolution)."

    async def run(self, org_id: str) -> dict:
        alert = await check_sales_drop(org_id)
        if not alert:
            return {"ok": True, "alert": None, "message": "Nenhum alerta (queda ≤12% ou sem dados)"}

        sent = await send_alert_via_evolution(org_id, alert)
        return {"ok": True, "alert": alert, "sent": sent}


TOOL_REGISTRY["proactive_alerts"] = {"code_reference": "aios.tools.proactive_alerts.ProactiveAlertsTool"}