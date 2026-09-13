# YouTube — Todos os Canais: Agentes Autônomos → Aplicação AIOS 100% Autônomo + HITL

**Canais pesquisados (15):** AI Engineer, Rafael Melgaço, Andrej Karpathy, Anwar Hermuche, Ben AI, Jake Van Clief, Brendan Jowett, Jack Roberts, Anthropic, OpenAI, Liam Evans, Liam Ottley, Leadgenman, Rafael Milagre, Tyler AI  
**Data:** 2026-09-12  
**Requisito guardado:** `docs/REQUISITO_AGENTES_100_AUTONOMOS_HITL.md` — todos os agentes 100% autônomos, HITL se necessário

---

## 1. AI Engineer (@aiDotEngineer — 520K)

**Vídeos:** `Don't Build Agents, Build Skills Instead` (Anthropic 1.4M), `Agentic AI Engineer` (Mutagent), `12-Factor Agents`, `Agent Reliability` playlist

**Insight:** Skills > Agents. Loop `spec→build→evaluate→diagnose→monitor→optimise` (eval-driven). 12-factor para confiabilidade.

**Aplicação AIOS:**
- Nosso `skills.py` já extrai `tool_pattern`, mas precisa auto-promover após 2 sucessos + `top-3` retrieval (U-Mem) — fazer
- `AutonomousAgent` já é `spec→build→evaluate` com `Evaluator` + `Reflection`
- **HITL:** `12-factor` exige `human approval` como factor — nosso `pending_actions` já é

---

## 2. Rafael Melgaço (@melgarafael — 20K) — BR

**Vídeos:** `Agentes Humanizados n8n + TomikFlows`, `Ecossistema de Negócios com IA` (Kiwicast 1h10)

**Insight:** Humanização = tom + empatia PT-BR vende mais que robô. Ecossistema > tool isolada.

**Aplicação AIOS:**
- `#ESTILO` PT-BR nativo + `Kokoro pf_dora/pm_alex` + `barge-in` = humanizado validado
- Ecossistema = `Flow Builder` (Zap+Voz+Dado) — já temos, só falta tour (feito)

---

## 3. Andrej Karpathy (@AndrejKarpathy — 1.3M) — ex-OpenAI/Tesla

**Vídeos:** `Deep Dive LLMs`, `Skill Issue: Code Agents, AutoResearch, Loopy Era` (961K), `Vibe Coding → Agentic Engineering`, `How I use LLMs`

**Frase:** *"I almost never write code myself anymore."* — agente escreve 90%

**Insight:** **Loopy Era** — agente em `while loop` com tools fecha pesquisa sozinho (`AutoResearch`: coleta dado, treina, avalia autônomo). **Vibe → Agentic:** não é prompt, é engenharia de harness.

**Aplicação AIOS:**
- `AutonomousAgent` 3 trials é **Loopy Era** — nosso `Data Scientist` com `feature store + lineage + python_sandbox` já é `AutoResearch` em miniatura
- **Harness** = `agent.py + autonomous_agent.py + orchestrator` — precisa ser tão bom quanto o modelo (Karpathy)

---

## 4. Anwar Hermuche (29K, dascia.academy) — BR

**Vídeos:** `RAG do Zero` (5.3K), `HARNESS: What makes AI AGENT actually work`, `Self-Evolving Memory in Claude Code + Obsidian` (61K), `CLAUDE CODE Aula Completa` (68K)

**Insight:** **Harness** é o que envolve o LLM (memória, tools, loop, guardrails) — sem harness bom, LLM bom falha. **RAG** base para agente especializado. **Self-Evolving Memory** (Karpathy Method) ingestão blog/vídeo → Obsidian → Claude que aprende sozinho.

**Aplicação AIOS:**
- Harness = `AutonomousAgent` + `memory.py` + `tools.py` + `tracing.py` — já tem `Evaluator+Reflection+hot buffer`
- RAG já tem `pgvector` + `chunk 800` — usar como `CONHECIMENTO` em 12 tags
- Self-Evolving = `U-Mem` dual-buffer + `Skill` auto-extração

---

## 5. Ben AI (@BenAI92 — 228K) — 2x $1M ARR

**Vídeos:** `Build an AI Agent Team That Does EVERYTHING (No-Code)` (153K, Manager+WhatsApp+Email+Calendar), `I Built MARKETING Team with 37 AI Agents`, `Claude Skills` (177K), `Polsia: AI agents autonomously build companies` ($30M, $9.5M ARR, 0 funcionários)

**Insight:** **Team de agentes** com Manager + Tools (WhatsApp, Email, Calendar) + **Ben Broca/Polsia** = agentes que **criam empresas sozinhos** (idea → build → Stripe → marketing → support) — **80% autônomo** vence quem não é.

**Aplicação AIOS:**
- Nosso `Team(orchestrator+manager+sdr+closer)` já é `Manager Agent` do Ben — só precisa `WhatsApp Trigger` + `Send Whatsapp Tool` + `Calendar Tool` (já temos via `ToolEngine`)
- Polsia valida **per-company memory + shared best practices** → nosso `extra_data["secrets"]` + `skills` compartilhadas por `org_id`

---

## 6. Jake Van Clief (@JEVanClief — 60K)

**Vídeos:** `Stop Building AI Agents. Use This Folder System Instead` (133K), `You're Automating The Wrong Layer` (30K people without frameworks), `Why I Stopped Building AI Agents and Started Using Claude Cowork`

**Insight:** **Controverso:** agentes são armadilha; **configure a fábrica, não o agente** — `CLAUDE.md` + 3 workspaces + markdown routing > agentes. **Abstraction: não automatize o que o próximo modelo dá de graça.**

**Aplicação AIOS:**
- Valida nosso `prompt 12 tags` + `CLAUDE.md` + `Flow Builder` como **fábrica** — não precisa agente para tudo. Mas quando precisa (WhatsApp objeção), use `AutonomousAgent`.
- **Don't automate wrong layer:** Não criar agente para `calculator` — use tool direto. Nosso `PROMPT_TAGS_ESTRUTURA.md` já separa `#FERRAMENTAS` com `quando:` explícito.

---

## 7. Brendan Jowett (@brendanautomation — 46K) — AU, Inflate AI

**Vídeos:** `Beginner's Guide To Building AI Agents (No-Code)` (Conversational vs Autonomous), `Build A WhatsApp AI Voice/Chat Agent In 15 Minutes`, `Claude Code For Beginners` (skills, hooks, automations), `AI Voice Agents` (Retell, ElevenLabs)

**Insight:** 4 partes do agente: `LLM + Prompting + Knowledge + Tools (APIs, MCP)` — **Conversational vs Autonomous** é escolha.

**Aplicação AIOS:**
- Nosso `Agent` já tem 4 partes: `llm_config` + `system_prompt` (12 tags) + `memory_config` (knowledge) + `tools` (MCP)
- Voice Agents com `Retell/ElevenLabs` — nosso `Kokoro` é self-hosted equivalente, `Retell AI` já suportado via `AIOS_VOICE_PROVIDER`

---

## 8. Jack Roberts (@Itssssss_Jack — 262K) — vendeu startup 60k clientes

**Vídeos:** `Claude Code Agentic OS… It self improves` (86K), `Hermes Agent 10X Better`, `100 hours of Hermes lessons`

**Insight:** **Agentic OS que se auto-melhora** — SO visual que rastreia custos, skills, memória e sugere o que construir. 2000+ skills, auto-melhorável.

**Aplicação AIOS:**
- Nosso `Team + AgentVersion + Health Tracker` é embrião. Jack valida OS auto-melhorável — `meta_agent.py` + `skills.py` precisa virar loop offline

---

## 9. Anthropic (@anthropic-ai — 764K)

**Vídeos:** `How We Build Effective Agents (Barry Zhang, 15:08)` — 95K, `Building more effective AI agents` (93K), `Tips for building AI agents` (580K)

**Insight (blog oficial):** **Workflows vs Agents** — comece simples (prompt chaining, parallelization), só aumente para autônomo quando necessário. **Clear tool docs + ACI (Agent-Computer Interface) + evals**.

**Aplicação AIOS:**
- Valida nossa decisão **Beta fechado com 2 P0** vs GA — não over-engineer. `Workflows` (DAG) para casos previsíveis, `AutonomousAgent` para objeções imprevisíveis.
- Tool docs: nosso `TOOL_REGISTRY` + `input_schema` já faz, mas precisa `pydantic` strict (P1 SWE)

---

## 10. OpenAI (@OpenAI)

**Vídeos:** `5 Lessons from Real-World AI Agent Deployments` (Agents SDK + Responses API), `Swarm/AgentKit`, `Codex Team: From Autocomplete to Autonomous Agents (30min)`

**Insight:** `Agents SDK` + `Responses API` (web search, file search, computer use) → agentes que planejam viagens, gerenciam finanças em 1 call. **Codex** agora trabalha 30min sozinho gerando PR.

**Aplicação AIOS:**
- Nosso `LiteLLM` + `OpenAI Swarm` já é `Responses API` — usar `Agents SDK` pattern: `orchestrator` + `subagents` com `handoff`
- Codex valida `autonomous: true` com `max_iterations 10` — nosso `MAX_TRIALS 3` é conservador, pode ir para 5

---

## 11. Liam Evans (@liamevansyt — 77K)

**Vídeos:** `These AI Agents Will 4X Your Business`, `I Replaced My Entire Sales Team With AI` (855 views)

**Insight:** **AI Agents 4X business** — foco em **client acquisition**: `AI lead gen + sales system` via GoHighLevel, `AI Sales System`.

**Aplicação AIOS:**
- Nosso `SDR + Closer` + `crm_create_deal` já é `4X` — Liam valida `follow up` autônomo dobra negócio. Nosso `follow-up` ainda manual — precisa `cron` para `lead_score` re-engajamento

---

## 12. Liam Ottley (@LiamOttley — 846K) — AAA model

**Vídeos:** `How to Build & Sell AI Agents: Ultimate Beginner's Guide` (3.8M), `This AI Technology Will Replace Millions`

**Insight:** Criador **AAA (AI Automation Agency)** 2023 — `Morningside AI`. 4 fases: Text → Voice → Brain-Computer → Predictive. **Voz + Brain-Computer** são próximas ondas.

**Aplicação AIOS:**
- Valida `Voice` (`Kokoro`) + `Muse Spark` (open-source) que já temos no 1-click. AAA model = nosso `white-label revenue share` (PMM C4)

---

## 13. Leadgenman (@LeadGenMan — 6.2K)

**Vídeos:** `Build AI Agents That Generate Qualified Leads 24/7` (<10min), `AI Agents for Real-Time Lead Generation`

**Insight:** Lead gen 24/7 via agente que **coleta Google Maps + Serper + Apify + personaliza email**.

**Aplicação AIOS:**
- Nosso `lead_score` + `http_request` (Serper) + `send_email` já faz — só falta `Google Maps` tool (Apify). Fácil adicionar `tool: apify_scrape`

---

## 14. Rafael Milagre (@RafaelMilagre — 7K, VIVER DE IA)

**Vídeos:** `Within 6 hours, my AI Agent was already working AUTONOMOUSLY (OpenClaw)`, `I created an AI-powered call center`, `Por que IA esquece o meio do prompt (e como resolver)` (1.1K), `Lead capture system — no developer`

**Insight:** **OpenClaw em 6h já autônomo**, `call center` que liga/atende/analisa sozinho, **esquece meio do prompt** (solução: chunk + RAG). **BR** — valida **PT-BR + lead capture** sem dev.

**Aplicação AIOS:**
- `OpenClaw 6h autônomo` = nosso `AutonomousAgent` 3 trials — valida que é possível em horas, não semanas
- `Esquece meio` = nosso `context_manager.compress_and_fit` + `chunk 800` + `top_k` — já temos, mas precisa `RAG` como `CONHECIMENTO` estável

---

## 15. Tyler AI (@TylerReedAI — 23K)

**Vídeos:** `How To Use AI Agents To Do ALL Your Work - CrewAI Course`, `Build AI Agents Team That Does EVERYTHING (No-Code)` (Ben AI confusão, mas Tyler é CrewAI), `Autogen + Mem0 Long Term Memory`, `Deploying Agentic AI Safely and Scalably`

**Insight:** **CrewAI + Mem0 (long-term memory)** + **Global Control Plane** (Tyler Jewell, Akka) — arquitetura fragmentada é crise, precisa **Global Agentic Control Plane** com `durability, state management, compliance, audit trails`.

**Aplicação AIOS:**
- Nosso `Control Plane` (`license.py` + `blacklist`) já é embrião de **Global Control Plane**. Tyler Jewell valida que precisa **cross-framework durability + audit** — nosso `audit log + SIEM webhook` já faz.
- `Mem0 + Autogen` = nosso `Memory` + `Agent` — valida `long term memory` para agente

---

## Síntese — Como todos convergem para AIOS 100% autônomo + HITL

| Padrão (todos os 15 canais) | AIOS como aplicar (já está) |
|------------------------------|------------------------------|
| **Skills > Agents** (AI Engineer, Jack) | `skills.py` auto-extrair após 2 sucessos |
| **Harness** (Anwar, Karpathy) | `autonomous_agent.py` + `memory` + `tools` = harness |
| **Loopy Era / AutoResearch** (Karpathy) | `Data Scientist` com `feature store` loop |
| **Humanizado PT-BR** (Rafael Melgaço/Milagre) | `Kokoro` + 12 tags PT-BR |
| **Team Manager + Tools** (Ben AI, Polsia) | `Team(orchestrator)` + `WhatsApp/Email/Calendar` tools |
| **Folders > Agents** (Jake Van Clief) | `prompt 12 tags` + `CLAUDE.md` como fábrica, agente só quando precisa |
| **Voice Agents** (Brendan) | `Kokoro` + `Retell` self-hosted |
| **Agentic OS self-improves** (Jack Roberts) | `AgentVersion` + `Health Tracker` → OS |
| **Workflows vs Agents** (Anthropic) | `Workflow DAG` para previsível, `Autonomous` para imprevisível |
| **Agents SDK** (OpenAI) | `LiteLLM` + `Swarm` → `handoff` |
| **4X Business** (Liam Evans) | `SDR+Closer` + `crm` → follow-up autônomo |
| **AAA** (Liam Ottley) | `white-label` + `Muse Spark` |
| **Lead Gen 24/7** (Leadgenman) | `http_request` + `Apify` |
| **6h Autônomo** (Rafael Milagre) | `AutonomousAgent` 3 trials |
| **Mem0 + Control Plane** (Tyler) | `MemoryArena` + `Control Plane` license |

**Todos validam requisito guardado:** `autonomous:true` default + HITL `>R$5k`/`delete`/`confidence<0.4`.

---

**Próximo:** Testar SDR autônomo com "tá caro" ao vivo?
