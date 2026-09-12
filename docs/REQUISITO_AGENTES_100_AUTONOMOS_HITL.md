# Requisito: Todos os Agentes 100% Autônomos com HITL

**Data:** 2026-09-12  
**Status:** GUARDADO — Requisito fixo do produto  
**Origem:** Pesquisa YouTube (Nate Herk, Jack Roberts, Alan Nicolas, Nic Saraev) + Papers Reflexion/ReAct/ELL

> **Decisão:** A partir de agora, **todo agente no AIOS é 100% autônomo** — loop `Thought → Action → Observation → Reflection → Retry` até completar objetivo. **HITL apenas quando necessário** (valor, risco, compliance).

---

## 1. O que significa 100% autônomo no AIOS

| Antes (chatbot+) | Agora (autônomo 100%) |
|------------------|------------------------|
| 1 mensagem → 1 resposta, para | Objetivo → loop até `done` verificado |
| Escolhe tool se mandar | Escolhe tool sozinho (ReAct) |
| Se falhar, para e espera humano | Reflete verbalmente, corrige e tenta de novo (Reflexion, até 3 trials) |
| Memória RAG passiva (top_k 5) | Memória autônoma: `hot buffer` + `top-3 rules` relevantes (U-Mem) + consolidação |
| Skill manual | Skill auto-extraída de trajetória de sucesso (ELL) |

**HITL: quando pausar para humano**

- **Valor:** `crm_update_deal > R$5k` (já existe `pending_actions`)
- **Risco:** `DELETE/DROP`, `pg_*`, `DELETE` S3 sem versioning, `send_email` em massa >100
- **Compliance:** fora da janela 24h WhatsApp sem template aprovado (erro 131047)
- **Incerteza crítica:** `confidence < 0.4` após 3 trials — pede humano
- **Nunca HITL por preguiça:** se for só "tá caro", ele contorna sozinho com ROI

**Fonte:** Nate Herk — `n8n Guardrails` (agente só executa se dentro de guardrails, senão HITL). Jack Roberts — `Agentic OS self-improves` com skills + memory + cost tracking.

---

## 2. YouTube — O que cada canal ensina e como aplicar

### Nate Herk (489K, 500+ agentes, n8n)
- **Vídeos chave:** `I built 500+ AI agents`, `Guardrails`, `AI Agents Are Overused`, `Vapi Voice Agent`
- **Padrão:** `Tools & Memory + Multi-Agent + Guardrails + RAG (4 métodos)`
- **Aplicação AIOS:** Nosso `Flow Builder` já é `n8n visual` + `guardrails` via `slowapi 60/min` + `HITL pending_actions`. Nate prova que **guardrails** são o que separa agente confiável de brinquedo. Aplicar: `TOOL_REGISTRY` com `pydantic` + `input_schema` + `HITL` já fazemos (P1 SWE), mas falta **guardrail explícito por tool** (ex: `sql_query` nunca sem `where org_id`).

### Jack Roberts (262K, vendeu startup 60k clientes, Hermes/Agentic OS)
- **Vídeos chave:** `Claude Code Agentic OS… It self improves` (86k views), `Hermes Agent 10X Better`, `100 hours of Hermes lessons`
- **Padrão:** `Agentic OS` — SO que **monitora custos, skills, memória e sugere o que construir** automaticamente. 2000+ skills, self-improving.
- **Aplicação AIOS:** Nosso `Team(orchestrator+manager)` + `AgentVersion` + `Health Tracker` já é embrião de OS. Jack valida: **OS deve ser auto-melhorável** — nosso `meta_agent.py` + `skills.py` precisa virar `OS loop` que roda offline (consolidação). Ideia: `Skills` auto-promovidas após 2 sucessos, `Memory` com `update/discard` via RL (Agentic Memory).

### Alan Nicolas (251K, Lendár[IA] 20k alunos, Brasil)
- **Vídeos chave:** `Semana Marketing com Claude Code`, `Second Brain com IA`
- **Padrão:** `Second Brain` + **PT-BR nativo** + marketing com agentes
- **Aplicação AIOS:** Valida nosso **PT-BR nativo** (`pm_alex/pf_dora` Kokoro) + **12 tags PT-BR** + `second brain` = `long_term memory` + `rag_search`. Alan mostra que brasileiro paga por **agente que fala como brasileiro**, não traduzido.

### Nic Saraev / Nick Saraev (496K, Maker School, $300K/mo)
- **Vídeos chave:** `AI Agents Full Course 2026 (2h)`, `The Most Overrated AI Agents`, `False autonomy, Unreliable execution, No tangible output`
- **Padrão:** Crítica a **falsa autonomia** — agente que diz "feito" sem verificar resultado real é brinquedo. Lista 7 sinais de agente inútil: `False autonomy, Unreliable, No output, Novelty, High maintenance, Commoditized, Non-urgent`.
- **Aplicação AIOS:** Nosso `WorkflowRun.status` hoje marca `done` quando engine retorna, não quando **verifica** (ex: deal realmente criado no CRM?). Nick valida nosso `Evaluator` deve **verificar** (ex: `SELECT` no DB para confirmar) antes de `done`. Também valida **Voz outbound** como serviço vendável ($1.5k) — nosso `voice-agent` já tem.

**Outros:** Jotform `What are Autonomous AI Agents` (autonomia, memória, adaptabilidade) e `The Autonomy Engine` (LLM in while loop + tools) — mesma conclusão.

---

## 3. Comportamento Autônomo no AIOS (WhatsApp)

**Exemplo: objeção "tá caro"**

```
Usuário (WhatsApp Evolution): "tá caro"
  → Agente SDR autônomo (flag autonomous:true)
    Trial 1: Thought "preciso contornar" → Action `lead_score` (70) → Observation score 70 → Thought "respondo preço" → Action `send` "R$249" → Evaluator: falha (sem ROI, sem SPIN)
    → Reflection: "Falei preço sem calcular ROI vs contratar SDR (R$8k). Próxima: usar calculator"
    → Memória episódica salva reflexão
    Trial 2: Thought + reflexão injetada → Action `calculator` (8000 vs 249) → Observation "economia 97%" → Action `send` "Entendo. Um SDR custa R$8k, AIOS R$249 — economia 97%. Quer ver simulação para teu volume?" → Evaluator: sucesso (ofereceu próxima ação)
    → Extrai Skill `contorno_ta_caro_v1` → hot buffer
  Próximo cliente "muito caro" → recupera top-3 rules (inclui reflexão anterior) → acerta no Trial 1
  Se valor >R$5k ou confidence <0.4 após 3 trials → cria `PendingAction` → HITL (humano aprova)
```

**Mesmo loop para Voz:** `barge-in` + `Whisper` → `Thought` → `tool` → `Kokoro` → `Evaluator` (silence detection) → retry.

---

## 4. Implementação no Código (já guardado)

- **Flag:** `Agent.governance_config.autonomous=true` ou `AgentVersion` com `autonomous`
- **Runtime:** `aios/core/autonomous_agent.py` (ReAct 3 trials + Reflection)
- **Memory:** `aios/core/memory.py` + `U-Mem` dual-buffer
- **Skills:** `aios/core/skills.py` + `ExpeL` top-3
- **Guardrails:** `aios/core/tools.py` + `slowapi` + `HITL pending_actions`
- **HITL:** `aios/core/approval.py` + `Team` handoff

**Guardado em:** `docs/AUTONOMOUS_AGENTS_RESEARCH.md` + `docs/AUTONOMOUS_AGENTS_YOUTUBE.md` + este arquivo

---

## 5. Próximo Passo

> Quer que eu transforme **um agente WhatsApp real** (ex: SDR) em 100% autônomo com 3 trials + reflexão + HITL >R$5k para você testar "tá caro" ao vivo?

Isso prova que não é chatbot.
