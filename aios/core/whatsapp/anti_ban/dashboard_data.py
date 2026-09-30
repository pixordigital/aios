"""Per-instance ban-risk report for the dashboard."""

import logging

from aios.core.whatsapp.anti_ban.connection_warmer import daily_limit
from aios.core.whatsapp.anti_ban.risk import score_from_events
from aios.core.whatsapp.anti_ban.signals import gather_counts

logger = logging.getLogger(__name__)

KINDS = ["ban_signal", "http_403", "http_429", "disconnect", "opted_out", "blocked", "sent"]


async def instance_report(org_id: str, instance: str, warmup_stage: int = 0,
                          curve: str = "conservative", connected: bool = True) -> dict:
    """Build one instance's risk card from the last 24h of real signals."""
    counts = await gather_counts(org_id, instance, days=1)

    # Velocity against the warmup curve: the biggest self-inflicted risk.
    cap = max(1, daily_limit(warmup_stage, curve))
    sent = int(counts.get("sent", 0))
    ratio = sent / cap if sent else 0.0

    report = score_from_events(counts, connected=connected, velocity_ratio=ratio)
    data = report.as_dict()
    data.update({
        "instance": instance,
        "sent_today": sent,
        "daily_cap": cap,
        "velocity_ratio": round(ratio, 2),
        "blocked_today": int(counts.get("blocked", 0)),
    })
    return data


async def org_report(org_id: str, instances: list, warmup_stage: int = 0) -> dict:
    """Worst-case rollup across instances — what the page header shows."""
    cards = [
        await instance_report(org_id, i, warmup_stage=warmup_stage)
        for i in instances
    ]
    worst = max(cards, key=lambda c: c["score"]) if cards else None
    return {
        "cards": cards,
        "worst": worst,
        "score": worst["score"] if worst else 0,
        "level": worst["level"] if worst else "green",
        "quarantined": any(c["quarantined"] for c in cards),
    }
