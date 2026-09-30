# AgentRuntime

> God node · 68 connections · `aios/core/agent.py`

**Community:** [Agent Runtime Loop](Agent_Runtime_Loop.md)

## Connections by Relation

### calls
- _process_inbound_once() `EXTRACTED`
- _get_runtime() `EXTRACTED`
- ._execute_node() `EXTRACTED`
- agent_run() `EXTRACTED`
- process_commitment_at_risk() `EXTRACTED`
- ._supervisor_route_stream() `EXTRACTED`
- _subagent_worker() `EXTRACTED`
- ._poll_loop() `EXTRACTED`
- ._round_robin() `EXTRACTED`
- ._semantic_route_stream() `EXTRACTED`
- sse_stream() `EXTRACTED`
- event_stream() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._round_robin_stream() `EXTRACTED`
- .test_agent_runtime_survives_stale_tool_name() `EXTRACTED`

### contains
- core/agent.py `EXTRACTED`

### imports
- app.py `EXTRACTED`
- jobs.py `EXTRACTED`
- conversations.py `EXTRACTED`
- eval.py `EXTRACTED`
- workflow.py `EXTRACTED`
- test_crm_tools.py `EXTRACTED`
- core/orchestrator.py `EXTRACTED`
- promptlab.py `EXTRACTED`
- autonomous_agent.py `EXTRACTED`
- subagent.py `EXTRACTED`
- email_.py `EXTRACTED`

### method
- .run_stream() `EXTRACTED`
- .run_structured() `EXTRACTED`
- ._syscall() `EXTRACTED`
- ._build_context() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._llm_chat_stream() `EXTRACTED`
- .run() `EXTRACTED`
- ._llm_chat() `EXTRACTED`
- .build_context() `EXTRACTED`
- ._spawn_subagent() `EXTRACTED`
- .load_project_skills() `EXTRACTED`

### rationale_for
- One agent loop per deployed agent. All LLM/memory/tool calls route through… `EXTRACTED`

### references
- 6. Arquiteto — OS como um todo (10min) `INFERRED`
- 2. Teste ao vivo — WhatsApp objeção (Voz Eng, 10min) `INFERRED`
- `manager` — Gerente Handoff + SLA (SWE Lead) `INFERRED`
- 5. Decisão `INFERRED`
- 4. WhatsApp/Voz — Voz e Evolution autônomos? (8min) `INFERRED`
- 3.2 Time — 5 Estratégias `INFERRED`
- `orchestrator` + `manager` — Roteamento `INFERRED`

### uses
- [DatabaseBackend](DatabaseBackend.md) `INFERRED`
- [Agent](Agent.md) `INFERRED`
- AutonomousAgent `INFERRED`
- Message `INFERRED`
- TeamOrchestrator `INFERRED`
- ToolEngine `INFERRED`
- MemoryManager `INFERRED`
- WorkflowEngine `INFERRED`
- HookContext `INFERRED`
- send_message_stream() `INFERRED`
- send_message() `INFERRED`
- HookPoint `INFERRED`
- EmailChannel `INFERRED`
- lab_agent_publish() `INFERRED`
- eval_agent() `INFERRED`
- SyscallType `INFERRED`
- agent_test() `INFERRED`
- sandbox_chat() `INFERRED`
- SyscallResponse `INFERRED`
- SyscallRequest `INFERRED`
- *…and 2 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*