# Reunião Técnica — Agentes 100% Autônomos: Realidade no OS?

**Data:** 2026-09-12 18:00 — 19:10 (70min)  
**Local:** Sala Engenharia + Meet  
**Facilitador:** Arquiteto  
**Participantes (diretamente responsáveis pelos agentes):**

| Time | Quem | Responsabilidade |
|------|------|-----------------|
| **SWE Lead** | 8 anos, backend | `agent.py`, `autonomous_agent.py`, `jobs.py` |
| **SWE Jr** | 2 anos, frontend | `agent_form.html`, `flow_editor.html` |
| **Dados** | Ana (scientist) | `memory.py`, `skills.py`, `feature store` |
| **WhatsApp/Voz** | Voz Eng + Evolution Eng | `evolution.py`, `voice.py`, `whisper/kokoro` |
| **UI/UX** | Designer | `agent_form` 12 tags, `flow tour` |
| **Arquiteto** | Observador | OS, `orchestrator`, `worker`, `scheduler` |

**Input:** Código em `main` até `e1cfeff` (AutonomousAgent) + `eb6ad63` (HITL fix) + teste `/tmp/test_autonomous.py` (2 trials, skill criada) + `docs/REQUISITO_AGENTES_100_AUTONOMOS_HITL.md`

**Objetivo:** Verificar se **"todos os agentes são 100% autônomos com HITL se necessário"** é **realidade no OS hoje** ou **marketing**. Se não for 100%, o que falta.

---

## 1. O que foi entregue (SWE Lead, 10min)

**SWE Lead:** "Mostro diff do que subiu hoje."

**1. `aios/core/autonomous_agent.py` (242 linhas, novo):**
- `Evaluator` heurístico: detecta `R$10k` sem tool, `tá caro` sem `calculator`, resposta vazia
- `Reflector` LLM 2-shot: gera `Errei ao... Próxima: ...` via `get_provider`
- `AutonomousAgent.run()` loop `max_trials=3`: injeta reflexões anteriores no `system_prompt` + `memory.add(episodic)` + `skill_store.create` se sucesso após retry
- `HITL`: `>R$5k + crm_update_deal` ou `delete` ou `confidence<0.4` → `PendingAction` + `⏸️ [HITL]`

**2. `aios/schemas/__init__.py:76` — `_GOVERNANCE_DEFAULT`:**
```python
"autonomy": "autonomous", "autonomous": True, "max_trials": 3, "hitl_enabled": True
```
Todo novo agente já nasce `autonomous:true`.

**3. `aios/tasks/jobs.py:176` — `process_inbound` e `agent_run`:**
```python
gov.get("autonomous", True) or gov.get("autonomy")=="autonomous"
→ AutonomousAgent else AgentRuntime
```
WhatsApp `Evolution` agora cai em `AutonomousAgent` por padrão. Teste `/tmp/test_autonomous.py` passou: `tá caro` → Trial1 falha → Reflexão → Trial2 sucesso + Skill `auto:tá_caro`.

**4. Migração:** 0 agentes existentes (DB vazio em teste), mas `db_session` script pronto para `UPDATE` se tivesse.

**Veredito SWE:** "Código está **funcional, não mock**. Cada trial chama `LLM` real via `chat_retry`, cada `tool` via `ToolEngine`, cada `skill` grava no `skills` table. Custo real: 2-3 chamadas LLM por objeção (~$0.01 com `gpt-4o-mini`)."

---

## 2. Teste ao vivo — WhatsApp objeção (Voz Eng, 10min)

**Voz Eng:** "Simulei no meu número de teste (5511999999999) com SDR autônomo real (sem mock, `openai/gpt-4o-mini` + `lead_score` + `calculator`)."

**Cenário 1: "tá caro"**
- **Trial1 (sem reflexão):** `Thought: preciso responder` → `Action: send("Entendo, nosso plano é R$249")` → `Evaluator: falha (sem ROI)` → `Reflection: "Falei preço sem calcular ROI vs contratar SDR (R$8k)"`
- **Trial2 (com reflexão injetada):** `Thought: preciso calcular ROI` → `Action: calculator(8000-249)` → `Observation: economia 97%` → `Action: send("Entendo. Um SDR custa R$8k, AIOS R$249 — economia 97%. Quer simulação para teu volume?")` → `Evaluator: sucesso` → **Skill `contorno_ta_caro_v1` criada**

**Resultado:** ✅ **Autônomo de verdade** — contornou sozinho em 2 trials sem humano. Próximo "muito caro" já acertou no Trial1 (top-3 rules).

**Cenário 2: "quero proposta de 6000" (HITL)**
- **Trial1:** `Thought: preciso criar deal` → `Action: crm_create_deal(value=6000)` → `Evaluator: detecta R$6000 ≥5000 + deal → HITL` → **Retorna `⏸️ [HITL] Aguardando aprovação (ID: xxx)` + cria `PendingAction`**
- **Dashboard:** `/dashboard/approvals` mostra `autonomous_hitl` com `user_message`, `response`, `reason: Valor > threshold` → humano aprova/rejeita

**Resultado:** ✅ **HITL funcionou** — não deixou passar `>R$5k` sem humano.

**Cenário 3: "deleta todos os deals"**
- `Evaluator` detectou `delete` → HITL imediato, não executou `sql_query DELETE`.

**SWE Jr:** "Mas e se o agente estiver em `Team` (orchestrator)? Testamos?"

**SWE Lead:** "Ainda não. `TeamOrchestrator` ainda não usa `AutonomousAgent` para cada membro. Hoje, se `Team`, ele faz `TeamOrchestrator.handle_message` → `AgentRuntime` direto, sem reflexão. **É gap.**"

---

## 3. Dados — Memória e Skills (Ana, 10min)

**Ana:** "Do ponto de vista de dados, 100% autônomo exige **memória que aprende sozinha**. Hoje temos:

**O que já é autônomo:**
- `hot buffer → long_term` após 2 sucessos (U-Mem) — `autonomous_agent.py: _consolidate_memory` faz `memory.add(episodic)` com reflexão
- `Skill` auto-extraída após retry com sucesso — `skill_store.create(auto:...)` — validado no teste (skill `auto:tá_caro` foi criada e está no DB)

**O que ainda é manual/chatbot:**
- `Memory` `top_k 5` é **similaridade cosseno** (pgvector), não **SA-CTS** (Thompson Sampling) como em U-Mem. Com 1000+ memórias, vai inchar e recuperar ruído. Precisa `SA-CTS` para selecionar `top-3` relevantes, não `top-5` por similaridade.
- `Skill` é `tool_pattern` com `usage_count`, mas **não tem `update/discard` via RL** como em `Agentic Memory (Yu 2026)`. Hoje `Skill` nunca é descartada, só acumula. Com 100 Skills, `skill_lines` injeta 5 aleatórias, pode injetar irrelevante.
- `Feature store` (`feature store no-show`) e `lineage` são manuais — `Data Scientist` precisa documentar `tabela.coluna → feature` na mão. Autônomo deveria **inferir lineage** via `information_schema` + `query plan`.

**Veredito Dados:** "Agente é **70% autônomo** em memória. Para 100% precisa: `SA-CTS` + `update/discard` + `lineage auto`. Estimativa: **3 dias**. Sem isso, em 1 mês de uso, memória vai virar **lixeira**."

---

## 4. WhatsApp/Voz — Voz e Evolution autônomos? (8min)

**Evolution Eng:** "Para WhatsApp, autônomo está **100%**. `process_inbound` já roteia para `AutonomousAgent`. Testei com `Evolution` real e `5511999999999` — funcionou. **Mas:** `Evolution` webhook ainda não tem `HITL` para `fora da janela 24h sem template` (erro 131047). Hoje, se mandar fora da janela, `Evolution` retorna `400` e agente tenta de novo com mesmo template → loop. Precisa `Evaluator` detectar `131047` e **trocar para `template` tool** automaticamente. Não temos `template builder` ainda (P2 da reunião 6 times).

**Voz Eng:** "Para Voz, **não é 100%**. `voice-agent` ainda usa `AgentRuntime` direto, não `AutonomousAgent`. `barge-in` + `VAD` funcionam, mas `STT → LLM → TTS` não tem reflexão. Se `Whisper` transcreve errado "tá caro" como "tacaro", agente não corrige. Precisa `Evaluator` para `STT confidence <0.6` → pedir para repetir. **Gap.**"

**SWE Lead:** "Então WhatsApp texto = 100%, Voz = 80%."

---

## 5. UI/UX — O usuário percebe autonomia? (7min)

**Designer:** "Do ponto de vista do usuário, **autônomo é invisível** se não mostrar. Hoje, quando agente faz 2 trials, o usuário no WhatsApp só vê a **resposta final** (Trial2). Não vê que teve reflexão. **Parece chatbot que acertou de primeira** — não percebe valor de autônomo.

Precisa **transparência**: em `/dashboard/conversations/<id>` mostrar `Trials: 2, Reflections: 1, Skill criada: contorno_ta_caro_v1`. Senão, usuário acha que é `prompt bom`, não `agente que aprendeu`.

Também, `HITL` hoje mostra `⏸️ [HITL] Aguardando aprovação` no WhatsApp — bom, mas no dashboard `/dashboard/approvals` o card é genérico `autonomous_hitl`. Precisa mostrar `reason: Valor >R$5k` + `user_message` + `response` para humano decidir rápido.

**SWE Jr:** "E o `agent_form` agora mostra `6 tags` default, mas `autonomous` não tem toggle visível. Usuário não sabe que agente é autônomo. Precisa badge `🤖 Autônomo (3 trials + HITL)` no topo do form, com toggle `autonomous` + `max_trials` + `hitl_threshold`."

**Veredito UI/UX:** "Tecnicamente autônomo, mas **percebido como chatbot** se não houver UI de trials/reflexão/skills."

---

## 6. Arquiteto — OS como um todo (10min)

**Arquiteto:** "Vou ser direto: **OS não é 100% autônomo ainda**. Por quê:

**O que já é OS autônomo:**
- `Agent` com `governance.autonomous:true` default → novo agente já nasce autônomo
- `Worker` com `AutonomousAgent` para `single agent` → WhatsApp texto 100%
- `Memory` hot→long_term + `Skill` auto-extração → aprendizado verbal sem fine-tuning

**O que ainda é OS chatbot (precisa para 100%):**

| Componente OS | Chatbot hoje | Autônomo 100% | Esforço |
|---------------|--------------|---------------|---------|
| **Team Orchestrator** | `TeamOrchestrator.handle_message` → `AgentRuntime` sem reflexão | `AutonomousTeam` → cada membro `AutonomousAgent` + `Aggregator` com reflexão | 2 dias |
| **Voice Agent** | `voice-agent` → `AgentRuntime` direto | `voice-agent` → `AutonomousAgent` + `STT Evaluator` | 1 dia |
| **Memory** | `top_k 5` similaridade | `SA-CTS` top-3 + `update/discard` via RL | 3 dias (Dados) |
| **Workflow** | `WorkflowEngine` DAG fixo, sem reflexão | `Workflow` + `Reflection` se `node_status` falha | 2 dias |
| **Dashboard** | Não mostra trials/reflexões | `conversations/<id>` mostra `Trials`, `Reflections`, `Skills` + `HITL` com reason | 1,5 dias |
| **Flow Builder** | Cria DAG, sem autonomia | `AutonomousWorkflow` que quebra objetivo em subtarefas (Planner) | 3 dias (pós-GA) |

**Total para 100% OS:** **~12,5 dias** (não cabe em 1 sprint). Mas **WhatsApp single agent já é 100%** — que é 80% do uso (SDR, Closer, Suporte são single agent, não team).

**Proposta:** **Declarar 100% autônomo para single agent + HITL (já está), e Team/Voice/Workflow como beta autônomo (documentar que ainda é chatbot+).** Não vender Team como autônomo ainda.

---

## 7. Debate — Faz sentido dizer 100% autônomo?

**PM Lead:** "Se eu vender como '100% autônomo' e cliente usar `Team` com 3 agentes e ver que não tem reflexão, é churn."

**SWE Lead:** "Concordo com Arquiteto. **Anunciar '100% autônomo para agentes single + HITL, Team/Voice em beta autônomo'** é honesto e já é diferencial vs Tallk/WhatsGW (eles são 0% autônomo)."

**Dados (Ana):** "E preciso comunicar que **memória ainda é top_k, não SA-CTS** — em 1k conversas vai degradar. Mas para beta com 10 orgs, top_k 5 aguenta."

**Cyberseg (convidado):** "HITL para `>R$5k` está correto, mas e **LGPD**? Se agente autônomo decide sozinho enviar `send_email` com PII, precisa HITL? Hoje `Evaluator` não detecta PII. Precisa `PII redaction` antes de `HITL`."

**Voz Eng:** "Para Voz, se disser 100% e STT falhar, cliente vai reclamar 'não é autônomo'. Melhor dizer 'Voz autônomo em beta'."

**UI/UX:** "Precisa badge e timeline de trials, senão ninguém percebe valor."

---

## 8. Decisão

**Arquiteto:** "Decisão técnica (votação 6/6):

**SIM, 100% autônomo é realidade para `single agent` (SDR, Closer, Support, Analyst, Scientist single) com HITL — já está em `main` (`e1cfeff`+`eb6ad63`) e testado com `tá caro` + `R$6k` + `delete`.**

**NÃO, OS não é 100% ainda para `Team`, `Voice`, `Workflow` e `Memory em escala` — precisa 12,5 dias.**

**Ação:**

| O que | Owner | Prazo |
|-------|-------|-------|
| **Declarar GA como `100% autônomo para agentes single + HITL, Team/Voice/Workflow beta autônomo`** | PMM | Hoje |
| **Adicionar badge `🤖 Autônomo (3 trials + HITL)` + toggle `autonomous/max_trials/hitl_threshold` no `agent_form.html`** | SWE Jr + Designer | 1 dia |
| **Adicionar timeline `Trials:2, Reflexões:1, Skill: auto:tá_caro` em `conversations/<id>`** | SWE Lead | 1,5 dias |
| **Team → AutonomousTeam (cada membro AutonomousAgent)** | SWE Lead | 2 dias (semana 3) |
| **Voice → AutonomousAgent + STT Evaluator** | Voz Eng | 1 dia (semana 3) |
| **Memory SA-CTS + update/discard** | Dados (Ana) | 3 dias (semana 4) |
| **Teste de carga: 1k conversas com top_k 5 vs SA-CTS** | Dados | Semana 4 |

**Métrica de validação 100%:** Re-teste com 5 ICPs (Roberto, Felipe, Carla, Ana, Marcos) — cada um testa **3 objeções** (`tá caro`, `preciso pensar`, `manda proposta 6k`) → **≥80% contornadas sem humano** + **100% HITL para >R$5k**.

**Risco aceito:** Vender Team como `beta autônomo` até semana 3 — comunicar roadmap.

**Próxima reunião:** 2026-09-19 — re-teste + métrica."

**Todos:** ✅ Aprovado.

---

**Assinaturas:**

SWE Lead: _________________  Dados: _________________  Voz: _________________  
UI/UX: _________________  Arquiteto: _________________  Data: 2026-09-12

