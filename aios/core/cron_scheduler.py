import asyncio
import json
import logging
import os
import subprocess
import pathlib
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_last_backup_day: str | None = None
_last_proactive_alert_day: str | None = None
_last_crm_mql_alert_day: str | None = None
_lock_sess = None

async def _tick():
    from aios.db.engine import async_session
    from aios.db.models import AutomationTrigger, Workflow, WorkflowRun
    from aios.db.rls import bind_session_rls, reset_rls_org_id
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    try:
        from croniter import croniter
    except ImportError:
        logger.warning("croniter not installed, cron scheduler disabled")
        return
    async with async_session() as sess:
        # Background jobs: pass org_id for RLS-enabled mode per trigger.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        trigs = (await sess.execute(select(AutomationTrigger).where(AutomationTrigger.type=="cron", AutomationTrigger.is_active==True))).scalars().all()
        for trig in trigs:
            rls_token = await bind_session_rls(sess, getattr(trig, "org_id", None))
            try:
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
            finally:
                if rls_token is not None:
                    reset_rls_org_id(rls_token)

def _backup_audit(action: str, details: dict) -> None:
    try:
        from aios.core.audit_sink import append as _audit_append

        _audit_append("system", action, {"component": "cron_scheduler.backup", **details})
    except Exception:
        logger.debug("backup audit sink failed action=%s", action, exc_info=True)


def _resolve_backup_script() -> pathlib.Path | None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    allowed = {
        (repo_root / "deploy" / "backup.sh").resolve(),
        pathlib.Path("/app/deploy/backup.sh").resolve(),
    }
    candidates = [
        repo_root / "deploy" / "backup.sh",
        pathlib.Path("/app/deploy/backup.sh"),
        pathlib.Path("deploy/backup.sh"),
    ]
    script = next((p for p in candidates if p.exists()), None)
    if script is None:
        return None
    resolved = script.resolve()
    if resolved.name != "backup.sh" or resolved not in allowed:
        _backup_audit("cron.backup.rejected", {"path": str(script), "resolved": str(resolved), "reason": "unexpected_path"})
        logger.error("backup.sh path rejected: %s resolved=%s", script, resolved)
        return None
    return resolved


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
    script = _resolve_backup_script()
    if not script:
        logger.warning("backup.sh not found or rejected, skipping daily backup")
        return
    _backup_audit("cron.backup.start", {"script": str(script)})
    logger.info("daily backup 03:00 trigger %s", script)
    try:
        proc = await asyncio.to_thread(
            subprocess.run, ["bash", str(script)], capture_output=True, text=True, timeout=600
        )
        logger.info("backup done rc=%s out=%.500s", proc.returncode, proc.stdout or "")
        if proc.returncode != 0:
            _backup_audit("cron.backup.failed", {"script": str(script), "rc": proc.returncode})
            logger.warning("backup failed rc=%s err=%.500s", proc.returncode, proc.stderr or "")
        else:
            _backup_audit("cron.backup.completed", {"script": str(script), "rc": proc.returncode})
    except Exception as e:
        _backup_audit("cron.backup.failed", {"script": str(script), "error": str(e)[:300]})
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
                async with async_session() as sess:
                    rls_token = await bind_session_rls(sess, org_id)
                    try:
                        from aios.tools.proactive_alerts import check_sales_drop

                        alert = await check_sales_drop(org_id)
                    finally:
                        if rls_token is not None:
                            reset_rls_org_id(rls_token)
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
            try:
                async with async_session() as sess:
                    rls_token = await bind_session_rls(sess, org_id)
                    try:
                        cutoff = datetime.now() - timedelta(days=7)
                        stale = (await sess.execute(
                            select(CrmDeal).where(
                                CrmDeal.org_id == org_id,
                                CrmDeal.stage == "mql",
                                CrmDeal.updated_at < cutoff,
                            )
                        )).scalars().all()
                        owner_ids = {d.agent_id for d in stale if d.agent_id}
                        owners = {}
                        if owner_ids:
                            owners = {a.id: a for a in (await sess.execute(select(Agent).where(Agent.id.in_(owner_ids)))).scalars().all()}
                    finally:
                        if rls_token is not None:
                            reset_rls_org_id(rls_token)
            except Exception:
                logger.exception("crm mql stale org query failed org=%s", org_id)
                continue

            for d in stale:
                owner = owners.get(d.agent_id) if d.agent_id else None
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
            try:
                async with async_session() as sess:
                    rls_token = await bind_session_rls(sess, org.id)
                    try:
                        from sqlalchemy import update

                        await sess.execute(
                            update(PendingAction)
                            .where(PendingAction.org_id == org.id, PendingAction.status == "pending", PendingAction.created_at < cutoff)
                            .values(status="expired")
                        )
                        await sess.commit()
                    finally:
                        if rls_token is not None:
                            reset_rls_org_id(rls_token)
            except Exception:
                logger.exception("expire_pending tick failed org=%s", org.id)
        logger.info("expire_pending tick done")
    except Exception:
        logger.exception("expire_pending tick failed")


async def _try_singleton_lock():
    """Take the Postgres advisory lock that elects the cron writer.

    run_once() is called by the ARQ cron in every worker process. Without the
    lock each worker would tick the same AutomationTrigger rows (the conditional
    UPDATE claim saves the workflow, but the per-process daily guards would
    still duplicate backup/proactive sweeps). The lock makes exactly one
    process the writer regardless of worker count.
    """
    from aios.db.engine import async_session
    from sqlalchemy import text as _t
    global _lock_sess
    sess = None
    try:
        sess = async_session()
        got = (await sess.execute(
            _t("SELECT pg_try_advisory_lock(:k)"), {"k": 0x41494F53}
        )).scalar()
        if not got:
            # The loser used to keep this session open forever: two idle-in-
            # transaction backends holding a transaction snapshot and a pooled
            # connection for the life of the process.
            await sess.close()
            return False
        # Session-level advisory locks survive COMMIT, and committing keeps the
        # winner out of "idle in transaction" (which pins an old snapshot and
        # blocks vacuum).
        await sess.commit()
        _lock_sess = sess
        return True
    except Exception:
        # SQLite (tests/local) has no advisory locks. Fall back to allowing it;
        # SQLite is single-process anyway.
        try:
            if sess is not None:
                await sess.close()
        except Exception:
            pass
        _lock_sess = None
        return True


async def run_once() -> None:
    """Run one scheduler iteration.

    Called by the ARQ cron in every worker. On Postgres the advisory lock elects
    one writer per tick; the loser returns without touching anything. SQLite has
    no advisory locks (and is single-process), so it just runs.
    """
    from aios.db.engine import engine

    global _lock_sess
    if engine.dialect.name.startswith("postgres"):
        if not await _try_singleton_lock():
            logger.debug("cron scheduler: another process holds the lock")
            return
    try:
        for step in (_tick, _backup_tick, _proactive_alerts_tick, _crm_mql_stale_tick, _expire_pending_tick):
            try:
                await step()
            except Exception:
                logger.exception("%s failed", step.__name__)
    finally:
        # Session-level lock dies with the connection; holding it between ticks
        # would pin a pooled connection for the life of the worker.
        if _lock_sess is not None:
            try:
                await _lock_sess.close()
            except Exception:
                pass
            _lock_sess = None
