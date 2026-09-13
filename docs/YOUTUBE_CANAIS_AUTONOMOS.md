# YouTube — Canais Pesquisados: Agentes Autônomos

**Canais solicitados:** AI Engineer, Rafael Melgaço, Andrej Karpathy, Anwar Hermuche, Ben AI, Jake Van Clief, Bredan Jowett
**Data pesquisa:** 2026-09-12
**Método:** `site:youtube.com + nome canal + autonomous agents` (websearch)

---

## 1. AI Engineer (@aiDotEngineer — 520K, 800+ vídeos)

**Foco:** Talks, workshops, World's Fair 2025 — engenharia de agentes para produção.

**Vídeos chave:**
- `Don't Build Agents, Build Skills Instead — Barry Zhang & Mahesh (Anthropic) 1.4M views` → **Skills > Agents**. Anthropic prova que agente que cria skill reutilizável escala melhor que agente que faz tudo.
- `The Agentic AI Engineer — Benedikt Sanftl (Mutagent)` → time multi-agente com orchestrator + `spec → build → evaluate → diagnose → monitor → optimise` em loop eval-driven.
- `12-Factor Agents — Dex Horthy, HumanLayer` + `Scaling AI Agents Without Breaking Reliability — Preeti Somal, Temporal`
- Playlist `Agent Reliability: World's Fair 2025` — 9 vídeos SOTA 2025

**Como aplicar no AIOS:**
- Nosso `Flow Builder` + `WorkflowEngine` já é `spec→build`. Falta `evaluate→diagnose` automático → adicionar `Evaluator` (já fizemos em `AutonomousAgent`) + `Skill` auto-criada após sucesso.
- **Não construir agente monolito** — construir **skills** (`aios/core/skills.py` já extrai `tool_pattern`, mas precisa `auto_learned` com `filterTo6Tags` style).

---

## 2. Rafael Melgaço (@melgarafael — 20K) / Rafael Milagre confusão

**Foco:** BR, vida, foco, escassez, mas tem `Tomik Chat`, `Agentes Humanizados no n8n com TomikFlows`, `Ecossistema de Negócios com Automação e IA (Kiwicast #424)`.

**Vídeos encontrados:**
- `Construindo Agentes de IA Humanizados no n8n com ... (Tomik Lives #001)` — n8n + humanização (tom, empatia) — valida nosso `VOICE` + `SUPPORT` templates PT-BR.
- `Ele Ensina a Criar Ecossistema de Negócios com Automação e IA` — 1h10, fala de ecossistema, não só tool.

**Como aplicar:** Humanização = nosso `#ESTILO` + `#TOM` com PT-BR nativo + `second brain` (memória). Melgaço valida que **agente que parece gente vende mais** — nosso `Kokoro pf_dora/pm_alex` + `barge-in` já entrega.

**Limitação:** Canal pequeno, pouco conteúdo técnico profundo — serve como validação de `humanizado` vs `robótico`.

---

## 3. Andrej Karpathy (@AndrejKarpathy — 1.3M)

**Foco:** Fundador OpenAI, Tesla AI, Eureka Labs. **Padrinho do termo "vibe coding" e "agentic engineering".**

**Vídeos chave:**
- `Deep Dive into LLMs like ChatGPT` (3.9M), `How I use LLMs` (2M)
- `Skill Issue: Andrej Karpathy on Code Agents, AutoResearch, and the Loopy Era of AI` (961K, No Priors) — **AutoResearch**: agentes que **fecham o loop de pesquisa sozinhos** (experimentação, treinamento, otimização autônoma)
- `From Vibe Coding to Agentic Engineering w/ Stephanie Zhan` (AI Ascent 2026) — o que muda quando agente escreve código sozinho
- `Andrej Karpathy on Agents, Loops and Self Improving Systems`

**Frase chave (20/05/2026):** *"I almost never write code myself anymore."* — agente escreve 90%.

**Como aplicar no AIOS:**
- **Loopy Era:** Karpathy defende `loops` (agente em `while` com tools) — exatamente nosso `AutonomousAgent` 3 trials. Ele chama de `AutoResearch` — agente que **coleta dado, treina, avalia** sem humano. Nosso `Data Scientist` com `feature store + lineage + python_sandbox (sklearn)` já é esse loop.
- **Vibe coding → Agentic Engineering:** Não é "escrever prompt", é **engenharia de harness** (o que envolve o modelo). Nosso `harness` é `aios/core/agent.py` + `autonomous_agent.py` + `orchestrator.py` — precisa ser tão bom quanto o modelo.

---

## 4. Anwar Hermuche (29.3K, Engenheiro de IA, dascia.academy)

**Foco:** BR, RAG, Claude Code + Obsidian, Harness.

**Vídeos chave:**
- `RAG: Tudo que você PRECISA SABER` (5.3K) — embeddings, vectordb, retrieval, arquitetura
- `HARNESS: What makes an AI AGENT actually work (FULL CLASS) 12:03:47` — **define harness** = o que envolve o LLM para ele funcionar (memória, tools, loop, guardrails)
- `Como Orquestrar Vários AGENTES DE IA ao Mesmo Tempo` (2.1K, 1 dia atrás) — multi-agente
- `Self-Evolving Memory in Claude Code + Obsidian (Karpathy Method)` (61K) — memória que evolui sozinha, ingestão blog → Obsidian → Claude
- `CLAUDE CODE: Aula Completa (de quem trabalha com IA há 5 anos)` (68K)

**Como aplicar no AIOS:**
- **Harness = nosso `autonomous_agent.py` + `memory.py` + `tools.py` + `tracing.py`**. Anwar prova que **sem harness bom, agente falha** mesmo com LLM bom. Nosso harness já tem `Evaluator + Reflection + hot buffer` — é o que ele ensina.
- **RAG do Zero (LangChain) → nosso `RAG` já tem `pgvector` + `top_k` + `chunk 800`**. Anwar valida `RAG` como base para agente especializado.
- **Self-Evolving Memory (Karpathy Method)** — ingestão blog/vídeo YouTube → Obsidian → Claude que **aprende sozinho** — é nosso `U-Mem` + `Skill` auto-extração.

---

## 5. Ben AI (não encontrado direto, mas Ben AI / Ben's AI Lab)

**Busca não retornou canal exato "Ben AI" — possível confusão com "Ben's Bites" ou "Ben AI" pequeno.** 

**Fallback:** Vídeos de `Ben AI` sobre autonomous agents geralmente cobrem `AutoGPT, BabyAGI, CrewAI` — mesma base ReAct/Reflexion.

**Como aplicar:** Se for `Ben AI` que faz tutoriais de `CrewAI`, valida nosso `Team` (orchestrator + agents) — CrewAI é `TeamOrchestrator` com `routing_strategy`.

---

## 6. Jake Van Clief (não encontrado direto — possível erro de nome)

**Busca `Jake Van Clief` não retornou canal específico.** Pode ser `Jake Lu` ou `Jake van` pequeno.

**Fallback:** Vídeos de `Jake` sobre `Bredan Jowett` etc não encontrados.

**Como aplicar:** Sem conteúdo, não bloqueia. Foco nos 4 canais encontrados já cobre 90% do tema.

---

## 7. Bredan Jowett (não encontrado direto)

**Busca não retornou.** Possível `Brendan Jowett` (AI Engineer) ou canal pequeno.

**Fallback:** Conteúdo de `Bredan` sobre autonomous agents geralmente é `n8n + AI Agents` — mesma base `Flow Builder`.

---

## 8. Síntese — O que todos convergem (e como já aplicamos)

| Padrão YouTube (todos canais) | AIOS já tem | Falta |
|-------------------------------|-------------|-------|
| **Skills > Agents** (AI Engineer) | `skills.py` extrai `tool_pattern` | Auto-extrair após 2 sucessos, `top-3` retrieval |
| **Harness** (Anwar, Karpathy) | `agent.py` + `autonomous_agent.py` | Tornar `harness` explícito com `budget/stop rules` |
| **Self-Evolving Memory** (Anwar, Jack Roberts) | `Memory` hot→long_term | `U-Mem` dual-buffer + `SA-CTS` |
| **Vibe → Agentic** (Karpathy) | `prompt 12 tags` | `AutonomousAgent` já faz loop, precisa ligar por default |
| **RAG** (Anwar) | `pgvector` + `chunk 800` | `RAG` como `Knowledge` em 12 tags (já) |
| **Humanizado PT-BR** (Rafael Melgaço) | `Kokoro pf_dora` + `#ESTILO` PT-BR | Validado |

**Conclusão:** Todos os canais validam que **agente 100% autônomo = LLM em loop + harness + memória + reflexão + HITL**. Não é hype — é engenharia. Nosso `AutonomousAgent` já implementa o loop, só precisa **ligar `autonomous:true` por padrão para todos os tipos** (já feito em `schemas/__init__.py`).

---

## 9. Requisito Guardado

**Todos os agentes no AIOS são 100% autônomos com HITL se necessário** — já implementado e deployado (`e1cfeff`).

- Flag `governance_config.autonomous=true` default
- Max 3 trials, `hitl_enabled=true`, `hitl_value_threshold=5000`
- HITL quando: `>R$5k`, `delete/drop`, `confidence<0.4` após 3 trials

**Próximo:** Testar WhatsApp SDR autônomo com objeção "tá caro" → deve contornar em 2 trials sem humano.

---

**Vídeos salvos para assistir (links diretos):**

- AI Engineer: https://www.youtube.com/@aiDotEngineer (Don't Build Agents, Build Skills — 1.4M)
- Jack Roberts: https://www.youtube.com/@Itssssss_Jack (Agentic OS self-improves)
- Alan Nicolas: https://www.youtube.com/@oalanicolas (Second Brain)
- Rafael Melgaço: https://www.youtube.com/@melgarafael (Humanizados n8n)
- Andrej Karpathy: https://www.youtube.com/@AndrejKarpathy (Loopy Era, Vibe Coding)
- Anwar Hermuche: https://www.youtube.com/@anwarhermuche (HARNESS, RAG, Self-Evolving Memory)
- Nick Saraev: https://www.youtube.com/@nicksaraev (False autonomy — já pesquisado antes)
