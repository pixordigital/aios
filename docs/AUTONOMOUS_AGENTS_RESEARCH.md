# Pesquisa: Agentes Autônomos de IA — Como Funcionam e Como Aplicar no AIOS

**Data:** 2026-09-12  
**Fontes:** ArXiv (Reflexion, ReAct, ReflAct, ELL, U-Mem), YouTube (15 vídeos), Docs OpenAI/Anthropic

---

## 1. O que é Agente Autônomo (vs Chatbot)

| Chatbot | Agente Autônomo |
|---------|-----------------|
| Reage a 1 mensagem → 1 resposta | Tem **objetivo** e age em loop até completar |
| Sem memória entre sessões | **Memória persistente** (curto + longo prazo) |
| Chama tool se você mandar | **Escolhe** tool sozinho via `ReAct` |
| Se falhar, para | **Reflete, corrige e tenta de novo** (Reflexion) |
| Precisa humano para próximo passo | **Planeja** próximos passos sozinho |

**Definição YouTube (Autonomy Engine, AI Made Simple):** Agente = `LLM em while loop com tools + memória + reflexão`. Não é chatbot com automação — é sistema que **percebe, raciocina e age** com autonomia.

---

## 2. Como Funciona — O Loop (YouTube + Papers)

### 2.1 Loop ReAct (base de tudo)

```
Enquanto não atingir objetivo:
  1. THOUGHT: "O que fazer agora? Preciso verificar budget"
  2. ACTION: chama tool `lead_score({budget: "10k"})`
  3. OBSERVATION: "score 85"
  4. Atualiza estado interno
  Repete
```

YouTube `ReAct AI Agents, clearly explained` e `Agentic AI Explained` mostram que é **Reasoning + Acting intercalados**. LLM decide próximo passo, não é workflow fixo.

### 2.2 Loop Reflexion (self-correction)

```
Trial 1: ReAct → falha (ex: alucina que tem item, mas não tem)
  → Heurística detecta "ineficiente" ou "alucinação"
  → LLM Reflexão: "Falei que tinha item mas inventário vazio, preciso checar antes"
  → Salva reflexão em memória episódica
Trial 2: ReAct + reflexão injetada → 97% AlfWorld (vs 75% sem)
```

YouTube `ReAct vs Reflexion` explica: **Reflexion = ReAct + memória verbal de falhas**. Custo zero (sem fine-tuning).

### 2.3 Loop ReflAct (world-grounded)

Reflexão ancorada no **estado do mundo + objetivo**, não só na trajetória. Permite **auto-correção no meio** da execução, não só pós-falha. 93,3% AlfWorld.

### 2.4 AutoGPT / BabyAGI (YouTube AutoGPT Tutorial)

- **AutoGPT:** recebe objetivo alto nível ("crie um SaaS"), quebra em subtarefas, executa em loop com `execute_python`/`browse` até completar. Limitação: sem memória de longo prazo → esquece.
- **BabyAGI:** Task queue priorizada + reflexão.

### 2.5 Memória Autônoma (U-Mem, MemInsight, Agentic Memory)

- **U-Mem (2026):** Agente decide **quando** buscar conhecimento externo (custo-aware) + **Semantic-Aware Thompson Sampling** para recuperar só top-3 relevantes — não inunda contexto.
- **MemInsight:** Augmentação autônoma de memória histórica → +34% recall LoCoMo.
- **Agentic Memory (2026):** `store/retrieve/update/summarize/discard` como **tools treinadas via RL (GRPO)** — supera RAG.

**YouTube `How AI Agents Actually Work (Tools, Memory, Planning & Failures)` resume:** Context ≠ State ≠ Memory. Context é janela, State é working memory, Memory é externo persistente com `retrieve` seletivo.

---

## 3. YouTube — Vídeos Chave e Comportamento

| Vídeo | O que ensina | Comportamento aplicável |
|-------|--------------|-------------------------|
| **Autonomy Engine How AI Agents Work** (22/03/2026) | Diferença zero-shot vs agentic workflow; think/plan/act/improve | AIOS já tem `plan→act`, falta `improve` (reflexão) |
| **How AI Agents Actually Work (Tools, Memory, Planning & Failures)** | Loop completo com falha → retry → human approval → verificação | Nosso `process_inbound` precisa `Evaluator` + `retry` + `human approval` antes de dizer `done` |
| **What are Autonomous AI Agents** | Autonomia, memória, adaptabilidade | Nosso `Memory` tem top_k 5 mas sem `update/discard` — precisa |
| **Agentic AI Explained (ReAct/Reflexion)** | Animação do loop + trade-offs | ReAct para SDR, Reflexion para objeção "tá caro" |
| **ReAct vs Reflexion** | Comparação direta | Reflexion é **evolução** de ReAct — adicionar reflexão pós-falha |
| **AutoGPT / BabyAGI / AgentGPT** | Goal → task decomposition → execution loop | Nosso `Workflow` (DAG) é **orquestração**, não decomposição autônoma — precisa `Planner` LLM |
| **Building Long-Running AI Agents (Anthropic/Sequoia)** | 3 motivos agentes perdem rumo: sem reflection, sem harness, sem memória | Nosso `harness` é `orchestrator.py` + `agent.py` — precisa `harness` mais robusto com `budget/stop rules` |
| **The Rise of Agentic AI** | Agentic = LLM in while loop + tools | Exatamente nosso `process_inbound` mas com `while not done` |

**Padrão YouTube comum:** Agente não diz "done" até **verificar** resultado real (ex: checar se deal foi criado no CRM, não só se tool retornou ok).

---

## 4. Como Aplicar no AIOS (WhatsApp)

### 4.1 Estado Atual (chatbot+)

- `aios/core/agent.py:462` — `system_prompt → LLM → tool → resposta`
- `aios/core/memory.py` — `short_term 50, long_term top_k 5, episodic summarize_after 10` — passivo
- `aios/core/orchestrator.py` — roteia para `sdr/closer/support` — sem reflexão
- `aios/core/skills.py` — extrai skill de sucesso, mas sem `ExpeL` top-3 retrieval
- **Falta:** loop autônomo, evaluator, reflexão, retry verbal

### 4.2 Arquitetura Autônoma Proposta (custo zero)

```
[WhatsApp Evolution] → dispatch_inbound → AutonomousAgent
  ├─ Planner (LLM): quebra "contornar objeção tá caro" em subtarefas
  ├─ Loop ReAct (max 3 trials):
  │   ├─ Thought → Action (tool) → Observation
  │   ├─ Evaluator (heurística): detecta alucinação (ex: prometeu desconto sem HITL) ou ineficiente (>3 turns sem tool)
  │   └─ Se falha → Reflexion LLM (2-shot) → salva em episodic memory → retry com reflexão injetada
  ├─ Memory Autônoma (U-Mem style):
  │   ├─ Hot buffer (recente) → promoção para long_term após 2 sucessos
  │   ├─ Retrieve top-3 rules relevantes (não tudo) → injetado no contexto
  │   └─ Consolidation offline (dual-buffer)
  └─ Skill Learning (ELL):
      └─ Abstrai trajetória sucesso → nova Skill reutilizável (ex: contorno_ta_caro_v1.py)
```

**Para WhatsApp "tá caro":**
- **Trial 1 (atual):** SDR responde "R$10k" → falha (sem ROI)
- **Reflexão:** "Precisei calcular ROI, não chutar preço"
- **Trial 2 (autônomo):** já com reflexão → `lead_score` + `calculator` (R$8k vs R$249) → contorna sozinho

### 4.3 Flags e Custos

- Flag `agent.autonomous=true` no `Agent` (ou `governance_config.autonomous`)
- Max 3 trials, timeout 30s por trial, budget 10k tokens — evita loop infinito (YouTube `guardrails & budgets`)
- Custo zero: sem fine-tuning, só prompt + memória verbal

### 4.4 Roadmap 2 Semanas

| Semana | Entrega | Base |
|--------|---------|------|
| 1 | `AutonomousAgent` (ReAct+Reflexion 3 trials) + `Evaluator` heurístico + `hot buffer` | Reflexion paper |
| 2 | `Skill` auto-extração (ExpeL) + `retrieve top-3` + dashboard "Memórias aprendidas" | ELL/U-Mem |

---

## 5. Vídeos YouTube Salvos (para assistir)

1. **The Autonomy Engine How AI Agents Work** — https://www.youtube.com/watch?v=y6PhkqdUTKU
2. **How AI Agents Actually Work (Tools, Memory, Planning & Failures)** — https://www.youtube.com/watch?v=iKMYbcb6NIY
3. **Agentic AI Explained: How AI Agents Actually Work** — https://www.youtube.com/watch?v=Ncn6X3WxN9g
4. **ReAct vs Reflexion** — https://www.youtube.com/watch?v=yYJiyYkOcVo
5. **Building a ReAct AI Agent (Tutorial)** — https://www.youtube.com/watch?v=f8whjxDBcd8
6. **Autonomous AI Agents: Auto-GPT, BabyAGI...** — https://www.youtube.com/watch?v=6Xzabc4IP70
7. **Anthropic Long-Running AI Agents & Harness Design** — https://www.youtube.com/watch?v=NRcbA3WYyp8

Transcripts e excerpts completos em `websearch` logs desta pesquisa.

---

## 6. Próximo Passo Imediato

> Quer que eu implemente `AutonomousAgent` com flag `autonomous:true` para seu agente WhatsApp testar "tá caro" → auto-correção?

Isso transforma SDR de `chatbot` para `agente que aprende sozinho com erros` — sem reescrever prompt manualmente.

**Guardado em:** `docs/AUTONOMOUS_AGENTS_RESEARCH.md` + `docs/AUTONOMOUS_AGENTS_YOUTUBE.md` (vídeos)
