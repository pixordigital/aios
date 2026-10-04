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
_last_crm_mql_alert_day: str | None = None
_lock_sess = None

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
                # Claim the trigger FIRST with a conditional UPDATE. Reading
                # next_run_at and advancing it afterwards let every worker that
                # polled the same due trigger fire it: with --workers 2 each cron
                # workflow ran twice and the customer got every automated message
                # twice. A conditional UPDATE is the lock -- the loser sees
                # rowcount 0 and skips.
                try:
                    from sqlalchemy import update as _update
                    _claim = await sess.execute(
                        _update(AutomationTrigger)
                        .where(
                            AutomationTrigger.id == trig.id,
                            AutomationTrigger.next_run_at <= now,
                        )
                        .values(next_run_at=croniter(trig.cron_expr, now).get_next(datetime),
                                last_run_at=now)
                    )
                    await sess.commit()
                    if _claim.rowcount == 0:
                        continue  # another worker already claimed this tick
                except Exception:
                    logger.exception("cron claim failed for trigger %s", trig.id)
                    continue
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
                    logger.exception("cron enqueue failed for trigger %s", trig.id)
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
    """Detect a sales drop and publish it as an event.

    This used to send the WhatsApp alert itself. Now it only reports the fact;
    which agent decides to act on it (and whether to message a human at all) is
    the agent's own governance. That is what makes the behaviour configurable
    per org and per agent instead of hardcoded here.
    """
    global _last_proactive_alert_day
    now = datetime.now(timezone.utc)
    # "At or after 08:00", not "during minute 0-1 of hour 8". The old exact-window
    # check meant one delayed tick, a restart or a long GC pause silently skipped
    # the whole day; combined with the in-process once-a-day guard below, nothing
    # would ever tell that org its sales dropped.
    if now.hour < 8:
        return
    today = now.date().isoformat()
    if _last_proactive_alert_day == today:
        return
    _last_proactive_alert_day = today
    logger.info("proactive alerts 08:00 trigger")

    try:
        from aios.db.engine import async_session
        from aios.db.models import Organization
        from sqlalchemy import select

        from aios.core.events import publish as publish_event

        async with async_session() as sess:
            orgs = (
                await sess.execute(
                    select(Organization.id).where(
                        Organization.is_active == True,
                        Organization.extra_data.op("->>")("proactive_alerts") == "true",
                    )
                )
            ).scalars().all()

            for org_id in orgs:
                try:
                    from aios.tools.proactive_alerts import check_sales_drop

                    alert = await check_sales_drop(org_id)
                    if not alert:
                        continue
                    await publish_event(
                        "sales.drop_detected",
                        org_id,
                        alert,
                        # Day-scoped so the daily check cannot fire the same
                        # drop twice if the tick is retried.
                        idempotency_key=f"sales-drop:{org_id}:{today}",
                    )
                    logger.info(
                        "sales.drop_detected published org=%s drop=%.1f%%",
                        org_id, alert.get("drop_pct", 0),
                    )
                except Exception as e:
                    logger.exception("sales drop check failed for org %s: %s", org_id, e)
    except Exception as e:
        logger.exception("Proactive alerts tick failed: %s", e)


async def _crm_mql_stale_tick():
    """Publish an event per deal stalled in MQL for 7+ days.

    Was: resolve the owner's phone and send WhatsApp directly. Now the stall is
    a fact on the bus, so an agent can decide to nudge the owner, re-score the
    deal, or do nothing. The phone lookup and message template move into the
    agent, which is where they belong.
    """
    global _last_crm_mql_alert_day
    now = datetime.now(timezone.utc)
    if now.hour < 9:
        return
    today = now.date().isoformat()
    if _last_crm_mql_alert_day == today:
        return
    _last_crm_mql_alert_day = today
    logger.info("crm mql stale 09:00 trigger")

    try:
        from aios.db.engine import async_session
        from aios.db.models import CrmDeal, Organization, Agent
        from sqlalchemy import select
        from datetime import timedelta

        from aios.core.events import publish as publish_event

        async with async_session() as sess:
            orgs = (await sess.execute(select(Organization.id).where(Organization.is_active == True))).scalars().all()
            for org_id in orgs:
                cutoff = datetime.now() - timedelta(days=7)
                stale = (await sess.execute(
                    select(CrmDeal).where(
                        CrmDeal.org_id == org_id,
                        CrmDeal.stage == "mql",
                        CrmDeal.updated_at < cutoff,
                    )
                )).scalars().all()

                for d in stale:
                    owner = await sess.get(Agent, d.agent_id) if d.agent_id else None
                    try:
                        await publish_event(
                            "crm.deal_stalled",
                            org_id,
                            {
                                "deal_id": d.id,
                                "lead_name": d.lead_name,
                                "lead_email": d.lead_email,
                                "pipeline": d.pipeline,
                                "value": float(d.value or 0),
                                "stage": d.stage,
                                "days_stalled": 7,
                                "owner_agent_id": d.agent_id or "",
                                "owner_agent_name": owner.name if owner else "",
                            },
                            idempotency_key=f"crm-stalled:{d.id}:{today}",
                        )
                    except Exception:
                        # One bad deal must not abort the org sweep.
                        logger.exception("crm.deal_stalled publish failed deal=%s", d.id)
    except Exception as e:
        logger.exception("CRM mql stale tick failed: %s", e)


async def _expire_pending_tick():
    """Daily 02:00 UTC — expira PendingAction alert-only por org pending_expiry_days (default 7)."""
    now = datetime.now(timezone.utc)
    if now.hour != 2 or now.minute not in (0, 1):
        return
    try:
        from aios.db.engine import async_session
        from aios.db.models import Organization, PendingAction
        from sqlalchemy import select

        async with async_session() as sess:
            orgs = (await sess.execute(select(Organization).where(Organization.is_active == True))).scalars().all()
            for org in orgs:
                try:
                    days = int((org.extra_data or {}).get("pending_expiry_days", 7))
                    if not 1 <= days <= 60:
                        days = 7
                except Exception:
                    days = 7
                cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - __import__("datetime").timedelta(days=days)
                # expira pending antigos
                from sqlalchemy import update

                await sess.execute(
                    update(PendingAction)
                    .where(PendingAction.status == "pending", PendingAction.created_at < cutoff)
                    .values(status="expired")
                )
                await sess.commit()
            logger.info("expire_pending tick done")
    except Exception:
        logger.exception("expire_pending tick failed")


async def _try_singleton_lock():
    """Hold a Postgres advisory lock for this process' scheduler lifetime.

    start_cron_scheduler() is called from the app lifespan, and lifespan runs
    once per gunicorn worker. With --workers 2 that meant two schedulers, and
    the module-level _last_backup_day / _last_proactive_alert_day guards were
    per-process, so the daily backup, the sales-drop alerts and the
    "deal parado ha 7+ dias" WhatsApp all fired twice. The advisory lock makes
    exactly one process the scheduler regardless of worker count.
    """
    from aios.db.engine import async_session
    from sqlalchemy import text as _t
    global _lock_sess
    try:
        _lock_sess = async_session()
        got = (await _lock_sess.execute(
            _t("SELECT pg_try_advisory_lock(:k)"), {"k": 0x41494F53}
        )).scalar()
        return bool(got)
    except Exception:
        # SQLite (tests/local) has no advisory locks. Fall back to allowing it;
        # SQLite is single-process anyway.
        try:
            if _lock_sess is not None:
                await _lock_sess.close()
        except Exception:
            pass
        _lock_sess = None
        return True


async def _loop():
    if not await _try_singleton_lock():
        logger.warning(
            "cron scheduler: another process holds the scheduler lock; this "
            "worker will not run cron ticks"
        )
        return
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
        try:
            await _crm_mql_stale_tick()
        except Exception:
            logger.exception("crm mql stale tick failed")
        try:
            await _expire_pending_tick()
        except Exception:
            logger.exception("expire_pending tick failed")
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
    # advisory lock is released when the session/connection closes
    if _task:
        _task.cancel()
