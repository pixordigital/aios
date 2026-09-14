"""Background learning worker — pattern extraction, memory consolidation, optimization.

Ruflo background-workers pattern: cron-like jobs that learn from every task.
Runs as ARQ cron alongside worker.py jobs, but focused on agent improvement.
"""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func, desc

from aios.db.backend import db_session
from aios.db.models import (
    Agent, AgentMetric, AgentLearning, AgentReflection,
    LearningJob, OptimizationRecord, Memory, Skill,
)

logger = logging.getLogger(__name__)


async def pattern_extraction_job(ctx):
    """Extract common success/failure patterns from recent reflections + learnings."""
    try:
        async with db_session() as db:
            # collect recent reflections
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
            refs = (await db.execute(
                select(AgentReflection).where(AgentReflection.created_at >= cutoff).limit(100)
            )).scalars().all()
            if not refs:
                return
            # naive pattern extraction: group by key_insight prefix
            insights: dict[str, int] = {}
            for r in refs:
                key = (r.key_insight or "")[:80].strip().lower()
                if key:
                    insights[key] = insights.get(key, 0) + 1
            # record top insights as learnings
            for text, cnt in sorted(insights.items(), key=lambda x: -x[1])[:5]:
                if cnt < 2:
                    continue
                exists = (await db.execute(
                    select(AgentLearning).where(
                        AgentLearning.trigger_context == text, AgentLearning.learning_type == "success_pattern"
                    ).limit(1)
                )).scalar_one_or_none()
                if exists:
                    continue
                db.add(AgentLearning(
                    agent_id=refs[0].agent_id, org_id=refs[0].org_id,
                    learning_type="success_pattern", trigger_context=text,
                    action_taken="reuse when similar task detected",
                    outcome=f"seen {cnt} times in 24h", success=True,
                    metrics={"count": cnt}, pattern_signature=text[:64],
                    confidence=min(0.5 + cnt * 0.1, 0.95),
                ))
            await db.commit()
            logger.info("pattern_extraction: %d patterns", len(insights))
    except Exception:
        logger.exception("pattern_extraction failed")


async def memory_consolidation_job(ctx):
    """Consolidate short-term memories into long-term knowledge where usage high."""
    try:
        async with db_session() as db:
            # promote frequently accessed memories via skill usage as example
            # for now: bump confidence on high-usage skills
            from aios.db.models import Skill
            skills = (await db.execute(
                select(Skill).where(Skill.usage_count >= 5).limit(20)
            )).scalars().all()
            for s in skills:
                # create a learning entry capturing the skill
                exists = (await db.execute(
                    select(AgentLearning).where(
                        AgentLearning.pattern_signature == s.id
                    ).limit(1)
                )).scalar_one_or_none()
                if exists:
                    continue
                db.add(AgentLearning(
                    agent_id=s.agent_id, org_id=s.org_id,
                    learning_type="skill_synthesis", trigger_context=s.name,
                    action_taken=s.content[:500], outcome=f"skill used {s.usage_count} times",
                    success=True, pattern_signature=s.id, confidence=s.success_rate,
                ))
            await db.commit()
            if skills:
                logger.info("memory_consolidation: %d skills consolidated", len(skills))
    except Exception:
        logger.exception("memory_consolidation failed")


async def optimization_review_job(ctx):
    """Review agent metrics for optimization opportunities."""
    try:
        async with db_session() as db:
            # find agents with high error rate or latency in last day
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
            metrics = (await db.execute(
                select(AgentMetric).where(AgentMetric.hour >= cutoff.strftime("%Y-%m-%d-%H")).limit(200)
            )).scalars().all()
            by_agent: dict[str, list] = {}
            for m in metrics:
                by_agent.setdefault(m.agent_id, []).append(m)
            for aid, rows in by_agent.items():
                total_m = sum(r.messages for r in rows) or 1
                total_e = sum(r.errors for r in rows)
                err_rate = total_e / total_m
                avg_lat = sum(r.avg_response_ms for r in rows) / len(rows) if rows else 0
                if err_rate > 0.08 or avg_lat > 4000:
                    # queue optimization record for review, don't auto-apply
                    exists = (await db.execute(
                        select(OptimizationRecord).where(
                            OptimizationRecord.agent_id == aid,
                            OptimizationRecord.created_at >= cutoff,
                        ).limit(1)
                    )).scalar_one_or_none()
                    if exists:
                        continue
                    db.add(OptimizationRecord(
                        agent_id=aid, org_id=rows[0].org_id,
                        optimization_type="prompt" if err_rate > 0.08 else "performance",
                        target_metric="success_rate" if err_rate > 0.08 else "latency",
                        before_value=err_rate if err_rate > 0.08 else avg_lat,
                        after_value=0, improvement_pct=0,
                        change_summary=f"flagged: err={err_rate:.1%} lat={avg_lat:.0f}ms",
                        validation_method="eval",
                    ))
            await db.commit()
    except Exception:
        logger.exception("optimization_review failed")


async def eval_review_job(ctx):
    """Review recent eval runs with low scores and create learnings."""
    try:
        async with db_session() as db:
            from aios.db.models import EvalRun
            runs = (await db.execute(
                select(EvalRun).where(EvalRun.avg_score < 0.6).order_by(desc(EvalRun.created_at)).limit(10)
            )).scalars().all()
            for run in runs:
                exists = (await db.execute(
                    select(AgentLearning).where(
                        AgentLearning.pattern_signature == f"eval_{run.id}",
                    ).limit(1)
                )).scalar_one_or_none()
                if exists:
                    continue
                db.add(AgentLearning(
                    agent_id=run.agent_id, org_id=run.org_id,
                    learning_type="failure_pattern", trigger_context=f"eval score {run.avg_score:.2f}",
                    action_taken="review prompt + tools; see eval results",
                    outcome=f"low score on dataset {run.dataset_id}", success=False,
                    metrics={"score": run.avg_score}, pattern_signature=f"eval_{run.id}",
                ))
            await db.commit()
    except Exception:
        logger.exception("eval_review failed")


# Export for ARQ cron registration (imported in worker.py)
CRON_JOBS = [
    ("pattern_extraction", pattern_extraction_job, "*/30 * * * *"),
    ("memory_consolidation", memory_consolidation_job, "0 */2 * * *"),
    ("optimization_review", optimization_review_job, "0 * * * *"),
    ("eval_review", eval_review_job, "15 * * * *"),
]
