# Team

> God node · 80 connections · `aios/db/models.py`

**Community:** [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md)

## Connections by Relation

### calls
- main() `EXTRACTED`
- test_message_kwargs_are_acceptable() `EXTRACTED`
- test_team_does_not_write_team_id_into_agent_id() `EXTRACTED`

### contains
- models.py `EXTRACTED`

### imports
- app.py `EXTRACTED`
- main.py `EXTRACTED`
- jobs.py `EXTRACTED`
- conversations.py `EXTRACTED`
- channels.py `EXTRACTED`
- crm2.py `EXTRACTED`
- api/voice.py `EXTRACTED`
- inbox.py `EXTRACTED`
- limits.py `EXTRACTED`
- teams.py `EXTRACTED`
- workflow.py `EXTRACTED`
- core/orchestrator.py `EXTRACTED`
- ws.py `EXTRACTED`
- gdpr.py `EXTRACTED`
- delivery.py `EXTRACTED`
- seed_internal_teams.py `EXTRACTED`
- core/swarm.py `EXTRACTED`
- test_reply_meta.py `EXTRACTED`

### inherits
- Base `EXTRACTED`
- TimestampMixin `EXTRACTED`
- OrgScopedMixin `EXTRACTED`

### references
- Reunião Técnica — Validação 100% Autônomo por Tipo de Agente `INFERRED`
- 3. Análise Detalhada — Por Componente `INFERRED`
- 4. Operacional — Dia a dia `INFERRED`
- 2. Teste ao vivo — WhatsApp objeção (Voz Eng, 10min) `INFERRED`
- 5 Patterns Zylos (Highest ROI = Reflection) `INFERRED`
- `manager` — Gerente Handoff + SLA (SWE Lead) `INFERRED`
- `orchestrator` — Roteamento (SWE Lead + Arquiteto) `INFERRED`
- 5. Veredito — Estão 100% autônomos? `INFERRED`
- 5. Decisão `INFERRED`
- 4. OS — Workflow, Voice, Memory (Arquiteto) `INFERRED`
- 5. Veredito — Estão 100% autônomos? `INFERRED`
- 8. Decisão `INFERRED`
- 6. Decisão `INFERRED`
- 4. Implementação no Código (já guardado) `INFERRED`
- 5. Ben AI (não encontrado direto, mas Ben AI / Ben's AI Lab) `INFERRED`
- 6. WhatsApp/Voz — “O que `Kokoro` + `Evolution` não entrega e `cliente` sente” `INFERRED`
- 4. Debate — É 100% autônomo ou não? (15min) `INFERRED`
- 7. Debate — Faz sentido dizer 100% autônomo? `INFERRED`
- 3.1 Single Agent — Todos os 8 Tipos `INFERRED`

### uses
- TeamOrchestrator `INFERRED`
- lifespan() `INFERRED`
- check_org_limits() `INFERRED`
- SwarmCoordinator `INFERRED`
- _process_inbound_once() `INFERRED`
- send_message_stream() `INFERRED`
- billing_page() `INFERRED`
- send_message() `INFERRED`
- deliver_message() `INFERRED`
- biweekly_1on1_job() `INFERRED`
- weekly_standup_job() `INFERRED`
- call() `INFERRED`
- dashboard_home() `INFERRED`
- admin_dashboard() `INFERRED`
- admin_org_detail() `INFERRED`
- voice_create() `INFERRED`
- delete_org() `INFERRED`
- create_team() `INFERRED`
- channel_edit_form() `INFERRED`
- team_list() `INFERRED`
- *…and 16 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*