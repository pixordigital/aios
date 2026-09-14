"""SPARC workflow engine — Spec, Pseudocode, Architect, Refine, Code, Test.

Ruflo SPARC pattern: structured 6-phase methodology for agentic software tasks.
Each phase produces output consumed by the next; loop up to N iterations.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import SparcWorkflow, SparcPhaseLog

logger = logging.getLogger(__name__)

PHASES = ["spec", "pseudocode", "architect", "refine", "code", "test", "refactor"]
PHASE_INDEX = {p: i for i, p in enumerate(PHASES)}
NEXT_PHASE = {PHASES[i]: PHASES[i + 1] for i in range(len(PHASES) - 1)}

PHASE_PROMPTS = {
    "spec": "Create a detailed specification for the task. Include requirements, constraints, success criteria.",
    "pseudocode": "Write pseudocode / algorithmic outline for the spec. Keep it language-agnostic.",
    "architect": "Design the architecture: modules, interfaces, data flow, error handling.",
    "refine": "Review pseudocode + architecture for gaps, over-engineering, edge cases. Suggest refinements.",
    "code": "Implement the code following the architecture. Concise, tested patterns.",
    "test": "Write tests / acceptance checks for the implementation. Include edge cases.",
    "refactor": "Review code + tests: simplify, remove duplication, improve naming.",
}


class SparcEngine:
    """Create and advance SPARC workflows."""

    async def create(
        self, *, org_id: str, name: str, description: str = "",
        agent_id: str | None = None, context: dict | None = None,
        max_iterations: int = 3,
    ) -> SparcWorkflow:
        async with db_session() as db:
            wf = SparcWorkflow(
                org_id=org_id, name=name, description=description,
                agent_id=agent_id, context=context or {}, max_iterations=max_iterations,
            )
            db.add(wf)
            await db.commit()
            await db.refresh(wf)
            return wf

    async def get(self, workflow_id: str) -> SparcWorkflow | None:
        async with db_session() as db:
            return await db.get(SparcWorkflow, workflow_id)

    async def list(self, *, org_id: str, limit: int = 20) -> list[SparcWorkflow]:
        async with db_session() as db:
            result = await db.execute(
                select(SparcWorkflow).where(SparcWorkflow.org_id == org_id)
                .order_by(SparcWorkflow.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def advance(
        self, *, workflow_id: str, phase_output: dict | None = None,
        agent_id: str | None = None,
    ) -> SparcWorkflow | None:
        """Complete current phase with output and move to next. Returns workflow."""
        async with db_session() as db:
            wf = await db.get(SparcWorkflow, workflow_id)
            if not wf or wf.status != "active":
                return None
            cur = wf.current_phase
            # save output for phase
            field = f"{cur}_output"
            if hasattr(wf, field) and phase_output is not None:
                setattr(wf, field, phase_output)
            wf.phase_status = "done"
            # log phase
            log = SparcPhaseLog(
                sparc_workflow_id=wf.id, org_id=wf.org_id, phase=cur,
                iteration=wf.iteration, input_context=dict(wf.context or {}),
                output=phase_output or {}, agent_id=agent_id or wf.agent_id,
                status="completed",
            )
            db.add(log)
            await db.flush()
            # move to next phase or next iteration
            nxt = NEXT_PHASE.get(cur)
            if nxt:
                wf.current_phase = nxt
                wf.phase_status = "pending"
                # pass context forward
                ctx = dict(wf.context or {})
                ctx[f"last_{cur}"] = phase_output or {}
                wf.context = ctx
            else:
                # end of phases → next iteration or done
                if wf.iteration < wf.max_iterations:
                    wf.iteration += 1
                    wf.current_phase = PHASES[0]
                    wf.phase_status = "pending"
                else:
                    wf.status = "completed"
                    wf.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            await db.refresh(wf)
            return wf

    async def fail_phase(
        self, *, workflow_id: str, error: str, agent_id: str | None = None,
    ) -> SparcWorkflow | None:
        async with db_session() as db:
            wf = await db.get(SparcWorkflow, workflow_id)
            if not wf:
                return None
            log = SparcPhaseLog(
                sparc_workflow_id=wf.id, org_id=wf.org_id, phase=wf.current_phase,
                iteration=wf.iteration, input_context=dict(wf.context or {}),
                output={}, agent_id=agent_id or wf.agent_id,
                status="failed", error=error,
            )
            db.add(log)
            wf.phase_status = "pending"  # allow retry
            await db.commit()
            await db.refresh(wf)
            return wf

    async def logs(self, workflow_id: str, limit: int = 50) -> list[SparcPhaseLog]:
        async with db_session() as db:
            result = await db.execute(
                select(SparcPhaseLog).where(SparcPhaseLog.sparc_workflow_id == workflow_id)
                .order_by(SparcPhaseLog.created_at.asc()).limit(limit)
            )
            return list(result.scalars().all())

    def phase_instruction(self, phase: str, workflow: SparcWorkflow | None = None) -> str:
        base = PHASE_PROMPTS.get(phase, phase)
        if workflow and workflow.context:
            # include recent phase outputs for continuity
            last = workflow.context.get(f"last_{PHASES[PHASE_INDEX[phase] - 1]}", {}) if phase in PHASE_INDEX and PHASE_INDEX[phase] > 0 else {}
            if last:
                base += f"\n\nPrevious phase output: {str(last)[:2000]}"
        return base

    PHASES = PHASES


sparc_engine = SparcEngine()
