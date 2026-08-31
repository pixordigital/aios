"""DAG workflow engine — directed graphs of agent/tool nodes.

Pattern: define workflow as graph, engine executes nodes respecting
dependencies, supports conditional branching and parallel fan-out.

ponytail: in-process executor. Add distributed execution (Celery/Temporal)
when workflows span processes.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text

from aios.core.agent import AgentRuntime

logger = logging.getLogger(__name__)


@dataclass
class WorkflowNode:
    id: str
    agent_id: str | None = None  # None = static tool call
    tool_name: str | None = None
    tool_args: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # node ids
    condition: str | None = None  # opt: python expr on previous results
    output_key: str = "result"  # key in shared context
    timeout: float = 60.0
    on_failure: str = "fail"
    retry_count: int = 0


@dataclass
class WorkflowDef:
    """Workflow definition — reused across runs."""

    id: str
    name: str
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    entry_node: str | None = None
    timeout: float = 120.0


class WorkflowResult:
    def __init__(self):
        self.outputs: dict[str, str] = {}
        self.errors: dict[str, str] = {}
        self.node_status: dict[str, str] = {}  # pending/running/done/skipped/failed

    def ok(self) -> bool:
        return not bool(self.errors)


_ORG_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _get_org_semaphore(org_id: str, limit: int = 8) -> asyncio.Semaphore:
    if org_id not in _ORG_SEMAPHORES:
        _ORG_SEMAPHORES[org_id] = asyncio.Semaphore(limit)
    return _ORG_SEMAPHORES[org_id]


class WorkflowEngine:
    """Execute DAG workflows. Parallel where dependencies allow."""

    def __init__(self, db_session_factory=None):
        self._db_factory = db_session_factory

    async def run(
        self,
        workflow: WorkflowDef,
        conv_id: str,
        initial_input: str,
        resume_outputs: dict | None = None,
        resume_status: dict | None = None,
    ) -> WorkflowResult:
        result = WorkflowResult()
        shared = {"initial_input": initial_input}
        if resume_outputs:
            result.outputs = dict(resume_outputs)
            shared.update(resume_outputs)
        if resume_status:
            result.node_status = dict(resume_status)
        ready = asyncio.Queue()
        pending = set(workflow.nodes.keys())
        if resume_status:
            for nid, st in resume_status.items():
                if st == "done" and nid in pending:
                    pending.discard(nid)
                    node = workflow.nodes.get(nid)
                    if node and resume_outputs and nid in resume_outputs:
                        shared[node.output_key] = resume_outputs[nid]
        running: dict[str, asyncio.Task] = {}
        run_id: str | None = None
        org_id_hint = ""

        async def _persist(status: str | None = None):
            if not run_id:
                return
            try:
                from aios.db.engine import async_session
                from aios.db.models import WorkflowRun

                async with async_session() as sess:
                    try:
                        await sess.execute(
                            text("SELECT pg_try_advisory_xact_lock(:k)"),
                            {"k": abs(hash(workflow.id)) % 2147483647},
                        )
                    except Exception:
                        pass
                    run = await sess.get(WorkflowRun, run_id)
                    if run:
                        if status:
                            run.status = status
                        run.node_status = dict(result.node_status)
                        run.outputs = dict(result.outputs)
                        if result.errors:
                            run.error = json.dumps(result.errors)[:4000]
                        try:
                            total = sum(len(str(v)) for v in result.outputs.values())
                            run.tokens = total // 4
                            from aios.core.tracing import estimate_cost

                            run.cost_usd = estimate_cost(
                                "openai/gpt-4o-mini", run.tokens
                            )
                        except Exception:
                            pass
                        await sess.commit()
            except Exception:
                logger.debug("WorkflowRun persist failed", exc_info=True)

        try:
            from aios.db.engine import async_session
            from aios.db.models import WorkflowRun

            async with async_session() as sess:
                existing = None
                try:
                    existing = await sess.get(WorkflowRun, conv_id)
                except Exception:
                    pass
                if existing and existing.workflow_id == workflow.id:
                    run_id = existing.id
                    org_id_hint = existing.org_id
                    existing.status = "running"
                    existing.inputs = {"input": initial_input}
                    existing.node_status = {nid: "pending" for nid in workflow.nodes}
                    await sess.commit()
                else:
                    run_id = str(uuid.uuid4())
                    try:
                        wf_org = None
                        from aios.db.models import Workflow as WFModel

                        wf = await sess.get(WFModel, workflow.id)
                        if wf:
                            wf_org = wf.org_id
                            org_id_hint = wf_org
                    except Exception:
                        pass
                    nr = WorkflowRun(
                        id=run_id,
                        workflow_id=workflow.id,
                        org_id=org_id_hint or "unknown",
                        conversation_id=conv_id,
                        status="running",
                        inputs={"input": initial_input},
                        outputs={},
                        node_status={nid: "pending" for nid in workflow.nodes},
                    )
                    sess.add(nr)
                    await sess.commit()
        except Exception:
            logger.debug("WorkflowRun create failed", exc_info=True)

        try:
            from aios.tasks.queue import enqueue

            await enqueue(
                "workflow_checkpoint",
                workflow_id=workflow.id,
                conv_id=conv_id,
                input=initial_input,
                run_id=run_id,
            )
        except Exception:
            pass

        for nid, node in workflow.nodes.items():
            if nid not in pending:
                result.node_status[nid] = result.node_status.get(nid, "done")
                continue
            result.node_status[nid] = "pending"
            if not node.depends_on or all(d not in pending for d in node.depends_on):
                await ready.put(nid)
                result.node_status[nid] = "ready"

        try:
            async with asyncio.timeout(workflow.timeout):
                while pending or running:
                    while not ready.empty():
                        nid = await ready.get()
                        if nid in running or nid not in pending:
                            continue
                        node = workflow.nodes[nid]
                        task = asyncio.create_task(
                            self._execute_node(node, conv_id, shared, result)
                        )
                        running[nid] = task

                    if not running:
                        if pending:
                            logger.warning(
                                "Workflow %s deadlock: pending=%s",
                                workflow.id,
                                pending,
                            )
                            for nid in list(pending):
                                result.node_status[nid] = "blocked"
                        break

                    done, _ = await asyncio.wait(
                        running.values(),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for d in done:
                        nid = next(k for k, v in running.items() if v is d)
                        running.pop(nid)
                        pending.discard(nid)
                        try:
                            node_result = d.result()
                            if node_result.ok:
                                shared[node.output_key] = node_result.outputs.get(
                                    node.id, ""
                                )
                            for nid2, node2 in workflow.nodes.items():
                                if nid in node2.depends_on and nid2 in pending:
                                    deps_done = all(
                                        d not in pending for d in node2.depends_on
                                    )
                                    if deps_done:
                                        await ready.put(nid2)
                            await _persist()
                        except Exception as e:
                            node = workflow.nodes.get(nid)
                            on_fail = getattr(node, "on_failure", "fail") if node else "fail"
                            if on_fail == "continue":
                                logger.warning("Workflow node %s failed but on_failure=continue: %s", nid, e)
                                result.node_status[nid] = "failed_continue"
                                result.errors.pop(nid, None)
                                for nid2, node2 in workflow.nodes.items():
                                    if nid in node2.depends_on and nid2 in pending:
                                        if all(d not in pending for d in node2.depends_on):
                                            await ready.put(nid2)
                            else:
                                logger.exception("Workflow node %s failed", nid)
                                result.errors[nid] = str(e)
                                result.node_status[nid] = "failed"
                            await _persist()

            for nid in pending:
                if result.node_status.get(nid) in ("pending", "ready"):
                    result.node_status[nid] = "skipped"

        except (TimeoutError, asyncio.TimeoutError):
            for nid, task in running.items():
                task.cancel()
                result.errors[nid] = "workflow timeout"
                result.node_status[nid] = "failed"

        await _persist("done" if result.ok() else "failed")
        return result

    async def _execute_node(
        self,
        node: WorkflowNode,
        conv_id: str,
        shared: dict,
        result: WorkflowResult,
    ) -> WorkflowResult:
        """Execute single node — either agent run or tool call."""
        result.node_status[node.id] = "running"
        if node.condition:
            try:
                import ast

                tree = ast.parse(node.condition, mode="eval")
                for n in ast.walk(tree):
                    if isinstance(n, (ast.Import, ast.ImportFrom, ast.Call)):
                        if (
                            isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Name)
                            and n.func.id
                            in ("__import__", "eval", "exec", "open", "compile")
                        ):
                            raise ValueError("blocked")
                if not eval(
                    compile(tree, "<cond>", "eval"),
                    {"__builtins__": {}},
                    {"shared": shared, "outputs": result.outputs},
                ):
                    result.node_status[node.id] = "skipped"
                    return result
            except ValueError as e:
                logger.warning("Workflow condition blocked %s: %s", node.id, e)
                result.node_status[node.id] = "skipped"
                return result
            except Exception as e:
                logger.warning("Workflow condition failed %s: %s", node.id, e)
                result.node_status[node.id] = "skipped"
                return result

        if node.agent_id:
            from aios.db.engine import async_session
            from aios.db.models import Agent as AgentModel

            agent_model = None
            try:
                async with async_session() as sess:
                    agent_model = await sess.get(AgentModel, node.agent_id)
                    if agent_model:
                        sess.expunge(agent_model)
            except Exception:
                pass
            if not agent_model:
                agent_model = type(
                    "obj",
                    (object,),
                    {
                        "id": node.agent_id,
                        "name": node.agent_id,
                        "llm_config": {
                            "model": "openai/gpt-4o",
                            "temperature": 0.5,
                            "max_tokens": 4096,
                        },
                        "system_prompt": shared.get("initial_input", ""),
                        "tools": [],
                        "memory_config": {},
                        "governance_config": {},
                        "org_id": "",
                    },
                )()
            runtime = AgentRuntime(agent_model, self._db_factory)
            msg = shared.get(node.output_key, shared.get("initial_input", ""))
            output = await runtime.run(conv_id, msg)
            result.outputs[node.id] = output
            result.node_status[node.id] = "done"
        elif node.tool_name:
            from aios.core.tools import ToolEngine

            engine = ToolEngine([node.tool_name])
            args_json = json.dumps(node.tool_args)
            org = (
                getattr(shared, "get", lambda k, d=None: d)("org_id")
                if isinstance(shared, dict)
                else ""
            )
            org = shared.get("org_id") or shared.get("initial_input_org") or ""
            sem = _get_org_semaphore(org or "global")
            try:
                async with sem:
                    output = await asyncio.wait_for(
                        engine.execute(node.tool_name, args_json), timeout=node.timeout
                    )
                result.outputs[node.id] = output
                result.node_status[node.id] = "done"
            except Exception as e:
                logger.exception("Workflow node execution failed: %s", node.id)
                result.errors[node.id] = str(e)
                result.node_status[node.id] = "failed"
                raise

        return result
