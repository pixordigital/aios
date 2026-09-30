# Agent

> God node · 153 connections · `aios/db/models.py`

**Community:** [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md)

## Connections by Relation

### calls
- _subagent_worker() `EXTRACTED`
- test_message_kwargs_are_acceptable() `EXTRACTED`
- _get_or_create_agent() `EXTRACTED`
- test_agent_still_writes_its_own_id() `EXTRACTED`
- .test_call_rejects_custom_agent() `EXTRACTED`

### contains
- models.py `EXTRACTED`

### imports
- app.py `EXTRACTED`
- main.py `EXTRACTED`
- jobs.py `EXTRACTED`
- workflows.py `EXTRACTED`
- analytics.py `EXTRACTED`
- conversations.py `EXTRACTED`
- agents.py `EXTRACTED`
- core/agent.py `EXTRACTED`
- channels.py `EXTRACTED`
- crm2.py `EXTRACTED`
- api/voice.py `EXTRACTED`
- routes.py `EXTRACTED`
- limits.py `EXTRACTED`
- admin_api.py `EXTRACTED`
- eval.py `EXTRACTED`
- cron_scheduler.py `EXTRACTED`
- teams.py `EXTRACTED`
- workflow.py `EXTRACTED`
- ws.py `EXTRACTED`
- test_features.py `EXTRACTED`
- *…and 17 more `imports` connection(s) not listed (lowest-degree first to go)*

### inherits
- Base `EXTRACTED`
- TimestampMixin `EXTRACTED`
- OrgScopedMixin `EXTRACTED`

### references
- 6. Arquiteto — OS como um todo (10min) `INFERRED`
- 2. BAA / DPA — LGPD (Encarregado + Medidas) `INFERRED`
- .__init__() `EXTRACTED`
- .__init__() `EXTRACTED`
- .__init__() `EXTRACTED`
- 15. Tyler AI (@TylerReedAI — 23K) `INFERRED`
- 4.3 Flags e Custos `INFERRED`
- 7. Brendan Jowett (@brendanautomation — 46K) — AU, Inflate AI `INFERRED`

### uses
- [AgentRuntime](AgentRuntime.md) `INFERRED`
- AutonomousAgent `INFERRED`
- WorkflowEngine `INFERRED`
- lifespan() `INFERRED`
- check_org_limits() `INFERRED`
- _register_syscall_handlers() `INFERRED`
- TestVoice `INFERRED`
- _process_inbound_once() `INFERRED`
- send_message_stream() `INFERRED`
- billing_page() `INFERRED`
- send_message() `INFERRED`
- deliver_message() `INFERRED`
- biweekly_1on1_job() `INFERRED`
- weekly_standup_job() `INFERRED`
- call() `INFERRED`
- crm_page() `INFERRED`
- dashboard_home() `INFERRED`
- lojista_create() `INFERRED`
- add_node() `INFERRED`
- admin_dashboard() `INFERRED`
- *…and 79 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*