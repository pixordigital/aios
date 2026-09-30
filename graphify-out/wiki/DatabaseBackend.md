# DatabaseBackend

> God node · 249 connections · `aios/db/backend.py`

**Community:** [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md)

## Connections by Relation

### contains
- db/backend.py `EXTRACTED`

### imports
- api/auth.py `EXTRACTED`
- deps.py `EXTRACTED`
- workflows.py `EXTRACTED`
- analytics.py `EXTRACTED`
- billing.py `EXTRACTED`
- conversations.py `EXTRACTED`
- agents.py `EXTRACTED`
- core/agent.py `EXTRACTED`
- channels.py `EXTRACTED`
- automations.py `EXTRACTED`
- crm2.py `EXTRACTED`
- api/voice.py `EXTRACTED`
- inbox.py `EXTRACTED`
- voice_recordings.py `EXTRACTED`
- eval.py `EXTRACTED`
- files.py `EXTRACTED`
- teams.py `EXTRACTED`
- memory.py `EXTRACTED`
- core/storage.py `EXTRACTED`
- api/tools.py `EXTRACTED`
- *…and 13 more `imports` connection(s) not listed (lowest-degree first to go)*

### inherits
- SQLAlchemyBackend `EXTRACTED`
- ConvexBackend `EXTRACTED`
- ABC `EXTRACTED`

### method
- .execute() `EXTRACTED`
- .get() `EXTRACTED`
- .health() `EXTRACTED`
- .add() `EXTRACTED`
- .commit() `EXTRACTED`
- .delete() `EXTRACTED`
- .flush() `EXTRACTED`
- .refresh() `EXTRACTED`
- .close() `EXTRACTED`

### rationale_for
- Abstract database backend. Implementations: SQLAlchemyBackend, ConvexBackend. `EXTRACTED`

### references
- [db_session()](db_session.md) `EXTRACTED`
- get_db_backend() `EXTRACTED`
- .handle_message() `EXTRACTED`
- ._supervisor_route() `EXTRACTED`
- .run_stream() `EXTRACTED`
- .handle_message_stream() `EXTRACTED`
- .run_structured() `EXTRACTED`
- ._hierarchical_route() `EXTRACTED`
- ._supervisor_route_stream() `EXTRACTED`
- _create_backend() `EXTRACTED`
- ._build_context() `EXTRACTED`
- ._hierarchical_route_stream() `EXTRACTED`
- ._round_robin() `EXTRACTED`
- ._semantic_route() `EXTRACTED`
- ._semantic_route_stream() `EXTRACTED`
- _fresh_backend() `EXTRACTED`
- ._broadcast() `EXTRACTED`
- ._round_robin_stream() `EXTRACTED`
- .run() `EXTRACTED`
- ._load_from_db() `EXTRACTED`
- *…and 5 more `references` connection(s) not listed (lowest-degree first to go)*

### uses
- [AgentRuntime](AgentRuntime.md) `INFERRED`
- get_current_user() `INFERRED`
- log_audit() `INFERRED`
- TeamOrchestrator `INFERRED`
- MemoryManager `INFERRED`
- register() `INFERRED`
- send_message_stream() `INFERRED`
- get_artifact_content() `INFERRED`
- save_artifact() `INFERRED`
- _oauth_login_or_register() `INFERRED`
- send_message() `INFERRED`
- login() `INFERRED`
- call() `INFERRED`
- list_artifacts() `INFERRED`
- webhook() `INFERRED`
- add_node() `INFERRED`
- upload_file() `INFERRED`
- read_artifact_text() `INFERRED`
- create_agent() `INFERRED`
- deploy_agent() `INFERRED`
- *…and 157 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*