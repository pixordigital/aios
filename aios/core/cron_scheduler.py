import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_running = False
_task: asyncio.Task | None = None

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

async def _loop():
    while _running:
        try:
            await _tick()
        except Exception:
            logger.exception("cron tick failed")
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
