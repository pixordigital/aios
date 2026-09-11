import asyncio
import json
import logging
import os
import subprocess
import pathlib
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_running = False
_task: asyncio.Task | None = None
_last_backup_day: str | None = None
_last_proactive_alert_day: str | None = None

async def _tick():
    from aios.db.engine import async_session
    from aios.db.models import AutomationTrigger, Workflow, WorkflowRun
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    try:
        from croniter import croniter
    except ImportError:
        logger.warning("croniter not installed, cron scheduler disabled")
        return
    async with async_session() as sess:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        trigs = (await sess.execute(select(AutomationTrigger).where(AutomationTrigger.type=="cron", AutomationTrigger.is_active==True))).scalars().all()
        for trig in trigs:
            should_run = False
            if trig.next_run_at is None and trig.cron_expr:
                try:
                    nxt = croniter(trig.cron_expr, now).get_next(datetime)
                    trig.next_run_at = nxt
                    await sess.commit()
                except Exception as e:
                    logger.warning("cron invalid %s: %s", trig.id, e)
                    continue
            if trig.next_run_at and trig.next_run_at <= now:
                should_run = True
            if should_run:
                wf = await sess.get(Workflow, trig.workflow_id, options=[selectinload(Workflow.nodes)])
                if not wf:
                    continue
                run = WorkflowRun(workflow_id=wf.id, org_id=trig.org_id, status="pending", inputs={"input": json.dumps({"trigger": "cron", "trigger_id": trig.id, "cron": trig.cron_expr}), "trigger_id": trig.id})
                sess.add(run)
                await sess.commit()
                await sess.refresh(run)
                try:
                    from aios.tasks.queue import enqueue_job
                    await enqueue_job("aios.tasks.jobs.workflow_run_job", {"workflow_id": wf.id, "run_id": run.id})
                except Exception:
                    pass
                try:
                    nxt = croniter(trig.cron_expr, now).get_next(datetime)
                    trig.next_run_at = nxt
                    trig.last_run_at = now
                    await sess.commit()
                except Exception:
                    pass
                logger.info("cron triggered workflow %s run %s", wf.id, run.id)

async def _backup_tick():
    """Daily 03:00 UTC backup via deploy/backup.sh (minimalista, aws cli opcional)."""
    global _last_backup_day
    if os.getenv("AIOS_BACKUP_ENABLED", "1") == "0":
        return
    now = datetime.now(timezone.utc)
    # run once at 03:00 UTC (window 03:00-03:01)
    if now.hour != 3 or now.minute not in (0, 1):
        return
    today = now.date().isoformat()
    if _last_backup_day == today:
        return
    _last_backup_day = today
    candidates = [
        pathlib.Path(__file__).resolve().parents[2] / "deploy" / "backup.sh",
        pathlib.Path("/app/deploy/backup.sh"),
        pathlib.Path("deploy/backup.sh"),
    ]
    script = next((p for p in candidates if p.exists()), None)
    if not script:
        logger.warning("backup.sh not found, skipping daily backup")
        return
    logger.info("daily backup 03:00 trigger %s", script)
    try:
        proc = await asyncio.to_thread(
            subprocess.run, ["bash", str(script)], capture_output=True, text=True, timeout=600
        )
        logger.info("backup done rc=%s out=%.500s", proc.returncode, proc.stdout or "")
        if proc.returncode != 0:
            logger.warning("backup failed rc=%s err=%.500s", proc.returncode, proc.stderr or "")
    except Exception as e:
        logger.exception("backup tick failed: %s", e)


async def _proactive_alerts_tick():
    """Daily 08:00 UTC proactive sales drop alerts via WhatsApp."""
    global _last_proactive_alert_day
    now = datetime.now(timezone.utc)
    # run once at 08:00 UTC (window 08:00-08:01)
    if now.hour != 8 or now.minute not in (0, 1):
        return
    today = now.date().isoformat()
    if _last_proactive_alert_day == today:
        return
    _last_proactive_alert_day = today
    logger.info("proactive alerts 08:00 trigger")

    try:
        from aios.db.engine import async_session
        from aios.db.models import Organization, ChannelConnection
        from sqlalchemy import select

        async with async_session() as sess:
            # Find orgs with proactive_alerts enabled AND active evolution channel
            orgs = (
                await sess.execute(
                    select(Organization.id).where(
                        Organization.is_active == True,
                        Organization.extra_data.op("->>")("proactive_alerts") == "true",
                    )
                )
            ).scalars().all()

            for org_id in orgs:
                # Verify active evolution channel exists
                has_evo = (
                    await sess.execute(
                        select(ChannelConnection.id).where(
                            ChannelConnection.org_id == org_id,
                            ChannelConnection.channel_type == "evolution",
                            ChannelConnection.is_active == True,
                        ).limit(1)
                    )
                ).scalar_one_or_none()
                if not has_evo:
                    continue

                try:
                    from aios.tools.proactive_alerts import check_sales_drop, send_alert_via_evolution
                    alert = await check_sales_drop(org_id)
                    if alert:
                        await send_alert_via_evolution(org_id, alert)
                        logger.info("Proactive alert sent for org %s: %.1f%% drop", org_id, alert.get("drop_pct", 0))
                except Exception as e:
                    logger.exception("Proactive alert failed for org %s: %s", org_id, e)
    except Exception as e:
        logger.exception("Proactive alerts tick failed: %s", e)


async def _loop():
    while _running:
        try:
            await _tick()
        except Exception:
            logger.exception("cron tick failed")
        try:
            await _backup_tick()
        except Exception:
            logger.exception("backup tick failed")
        try:
            await _proactive_alerts_tick()
        except Exception:
            logger.exception("proactive alerts tick failed")
        await asyncio.sleep(60)

def start_cron_scheduler():
    global _running, _task
    if _running:
        return
    _running = True
    _task = asyncio.create_task(_loop())
    logger.info("cron scheduler started")

def stop_cron_scheduler():
    global _running, _task
    _running = False
    if _task:
        _task.cancel()
