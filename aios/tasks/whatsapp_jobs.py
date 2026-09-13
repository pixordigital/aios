import logging
from aios.core.whatsapp.anti_ban.health_monitor import compute
from aios.core.whatsapp.migration_advisor import evaluate
logger = logging.getLogger(__name__)

async def health_monitor_aggregate():
    # Stub: itera instâncias Evolution e computa risk
    from aios.core.evolution_api import evo_fetch_instances
    instances = await evo_fetch_instances()
    for inst in instances:
        name = inst.get("instanceName") or inst.get("name") or ""
        h = compute(name, connected=inst.get("state")=="open", fails_24h=0, qr=0, r429=0)
        if h["quarantined"]: logger.warning("quarantine %s risk=%s", name, h["risk"])

async def migration_advisor_check():
    # Stub diario 09:00
    from aios.core.evolution_api import evo_fetch_instances
    for inst in await evo_fetch_instances():
        name = inst.get("instanceName") or ""
        rec = evaluate(monthly_msgs=1200, ban_risk=65, failed_pct=2)
        if rec.should_migrate: logger.info("migration recommend %s %s %s", name, rec.urgency, rec.reasons)
