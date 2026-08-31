"""ARQ worker entry point — processes background jobs.

Starts an ARQ worker that picks up queued jobs from Redis.
Registered jobs in aios.tasks.jobs.FUNCTIONS.
Reads Redis URL from settings.redis_url or REDIS_URL env.

Usage:
    python -m aios.tasks.worker
    aios-worker
"""

import os
from arq import cron
from arq.connections import RedisSettings
from aios.config import settings
from .jobs import FUNCTIONS


def _parse_redis(redis_url: str) -> RedisSettings:
    """Parse redis:// URL into RedisSettings."""
    from urllib.parse import urlparse
    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password or None,
    )


async def backup_job(ctx):
    import datetime
    import shlex
    import subprocess

    pg = os.getenv("AIOS_DATABASE_URL") or settings.database_url
    d = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = f"/data/backups/aios_{d}.sql.gz"
    os.makedirs("/data/backups", exist_ok=True)
    try:
        subprocess.run(f"pg_dump {shlex.quote(pg)} | gzip > {shlex.quote(out)}", shell=True, check=True, timeout=600)
    except Exception:
        pass


async def approval_expire_job(ctx):
    try:
        from aios.core.approval import approval_manager

        n = approval_manager.cancel_expired()
        if n:
            import logging

            logging.getLogger(__name__).info("Expired %d approvals", n)
    except Exception:
        pass


async def autoscale_job(ctx):
    try:
        from aios.db.engine import async_session
        from aios.db.models import Organization
        from sqlalchemy import select

        from aios.core.autoscaling import check_autoscale

        async with async_session() as sess:
            orgs = (await sess.execute(select(Organization))).scalars().all()
            for org in orgs[:20]:
                await check_autoscale(org.id)
    except Exception:
        pass


async def canary_rollback_job(ctx):
    try:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from aios.db.engine import async_session
        from aios.db.models import AgentInstance, AgentMetric

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        async with async_session() as sess:
            rows = (
                await sess.execute(
                    select(AgentInstance).where(AgentInstance.status == "running")
                )
            ).scalars().all()
            for inst in rows:
                extra = inst.extra_data or {}
                if not extra.get("canary"):
                    continue
                deployed_at = extra.get("deployed_at")
                try:
                    if deployed_at:
                        dt = datetime.fromisoformat(deployed_at.replace("Z", "+00:00"))
                        if dt > cutoff:
                            continue
                except Exception:
                    continue
                metrics = (
                    await sess.execute(
                        select(AgentMetric)
                        .where(AgentMetric.agent_id == inst.agent_id)
                        .order_by(AgentMetric.hour.desc())
                        .limit(3)
                    )
                ).scalars().all()
                if not metrics:
                    continue
                total_m = sum(m.messages for m in metrics) or 1
                total_e = sum(m.errors for m in metrics)
                err_rate = total_e / total_m
                if err_rate > 0.05 or any(m.avg_response_ms > 5000 for m in metrics):
                    inst.status = "stopped"
                    q = await sess.execute(
                        select(AgentInstance).where(
                            AgentInstance.agent_id == inst.agent_id,
                            AgentInstance.status == "stopped",
                        )
                    )
                    prev = q.scalars().first()
                    if prev and prev.id != inst.id:
                        prev.status = "running"
                    await sess.commit()
                    import logging

                    logging.getLogger(__name__).warning(
                        "Canary auto-rollback agent %s err=%.1f%%", inst.agent_id, err_rate * 100
                    )
    except Exception:
        pass


class WorkerSettings:
    functions = FUNCTIONS + [backup_job, approval_expire_job, autoscale_job, canary_rollback_job]
    cron_jobs = [
        cron(backup_job, hour=3, minute=0),
        cron(approval_expire_job, minute=5),
        cron(autoscale_job, minute=0),
        cron(canary_rollback_job, minute=10),
    ]
    redis_settings = _parse_redis(settings.redis_url or os.getenv("REDIS_URL", "redis://localhost:6379"))
    max_jobs = 20
    job_timeout = 300
    poll_delay = 0.2
    health_check_interval = 60
    log_results = True
    keep_result = 3600
    retry_jobs = True

    @staticmethod
    async def on_startup(ctx):
        from aios.db.engine import init_db
        try:
            await init_db()
        except Exception:
            pass

    @staticmethod
    async def on_shutdown(ctx):
        from aios.tasks.queue import close_pool
        try:
            await close_pool()
        except Exception:
            pass


# ponytail: async def run() kept for backward compat with aios-worker script
async def run():
    """Entry point for ``aios-worker`` script — blocks on event loop."""
    from arq.worker import Worker
    worker = Worker(functions=FUNCTIONS, redis_settings=WorkerSettings.redis_settings)
    await worker.run()


def main():
    """CLI entry point — uses arq's built-in worker loop."""
    from arq.cli import run_worker
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
