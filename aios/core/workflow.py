"""DAG workflow engine — directed graphs of agent/tool nodes.

Pattern: define workflow as graph, engine executes nodes respecting
dependencies, supports conditional branching and parallel fan-out.

ponytail: in-process executor. Add distributed execution (Celery/Temporal)
when workflows span processes.
"""

import asyncio
import logging
from dataclasses import dataclass, field

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


class WorkflowEngine:
    """Execute DAG workflows. Parallel where dependencies allow."""

    def __init__(self, db_session_factory=None):
        self._db_factory = db_session_factory

    async def run(self, workflow: WorkflowDef, conv_id: str, initial_input: str) -> WorkflowResult:
        result = WorkflowResult()
        shared = {"initial_input": initial_input}
        ready = asyncio.Queue()
        pending = set(workflow.nodes.keys())
        running: dict[str, asyncio.Task] = {}

        # seed ready nodes (no deps or all deps satisfied)
        for nid, node in workflow.nodes.items():
            result.node_status[nid] = "pending"
            if not node.depends_on:
                await ready.put(nid)
                result.node_status[nid] = "ready"

        try:
            async with asyncio.timeout(workflow.timeout):
                while pending or running:
                    # launch ready nodes
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
                        break  # deadlock

                    # wait for first completion
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
                                shared[node.output_key] = node_result.outputs.get(node.id, "")
                            # unblock dependents
                            for nid2, node2 in workflow.nodes.items():
                                if nid in node2.depends_on and nid2 in pending:
                                    deps_done = all(
                                        d not in pending for d in node2.depends_on
                                    )
                                    if deps_done:
                                        await ready.put(nid2)
                        except Exception as e:
                            logger.exception("Workflow node %s failed", nid)
                            result.errors[nid] = str(e)
                            result.node_status[nid] = "failed"

            # mark still-pending as skipped
            for nid in pending:
                result.node_status[nid] = "skipped"

        except TimeoutError:
            for nid, task in running.items():
                task.cancel()
                result.errors[nid] = "workflow timeout"
                result.node_status[nid] = "failed"

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

        if node.agent_id:
            # mock agent runtime — real impl would load from DB
            agent_model = type("obj", (object,), {
                "id": node.agent_id,
                "name": node.agent_id,
                "llm_config": {"model": "openai/gpt-4o", "temperature": 0.5, "max_tokens": 4096},
                "system_prompt": shared.get("initial_input", ""),
                "tools": [],
                "memory_config": {},
            })()
            runtime = AgentRuntime(agent_model, self._db_factory)
            msg = shared.get(node.output_key, shared.get("initial_input", ""))
            output = await runtime.run(conv_id, msg)
            result.outputs[node.id] = output
            result.node_status[node.id] = "done"
        elif node.tool_name:
            from aios.core.tools import ToolEngine
            engine = ToolEngine([node.tool_name])
            args_json = json.dumps(node.tool_args)
            try:
                output = await engine.execute(node.tool_name, args_json)
                result.outputs[node.id] = output
                result.node_status[node.id] = "done"
            except Exception as e:
                logger.exception("Workflow node execution failed: %s", node.id)
                result.errors[node.id] = str(e)
                result.node_status[node.id] = "failed"
                raise

        return result


import json  # noqa: E402 (needed for tool args serialization, kept after class)
