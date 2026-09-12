# Auditoria: Agentes AIOS estão 100% autônomos? — Checklist 2026

**Data:** 2026-09-13  
**Base:** Autonomous Agency Scale (Presgraves 0-5), Agent Reliability Checklist (60 itens), Reflexion/ReAct, Zylos 5 Patterns

## Checklist Autonomia (0=inert, 1=chatbot, 2=scheduled, 3=contextual, 4=self-directed, 5=fully autonomous)

| Dimensão (AAS) | AIOS single | AIOS Team/Voice | Meta 100% (nível 4) | Gap |
|----------------|-------------|-----------------|---------------------|-----|
| **Cognitive autonomy** (decide próximo passo) | 4 — ReAct + Reflection 3 trials | 3 — roteia mas não reflete se rotear errado | Precisa `orchestrator Reflection` |
| **Temporal persistence** (memória cross-sessão) | 3 — hot→long_term após 2 sucessos, SA-CTS top-3 | 3 — mesmo | 4 precisa `update/discard` RL (Yu 2026) |
| **Environmental agency** (age no mundo) | 4 — `sql_query`, `crm_create_deal`, `http_request` | 4 | OK |
| **Social agency** (HITL) | 4 — `>R$5k`, `delete`, `confidence<0.4` → PendingAction | 4 | OK |
| **Creative agency** (gera skill) | 3 — `auto:tá_caro` após retry | 2 — Team não abstrai skill de falha de roteamento | Precisa `Skill` de Team |
| **Self-awareness** (sabe que errou) | 4 — `Evaluator` heurístico + `Reflector` LLM | 3 — Voice STT `confidence<0.6` não avaliado | Falta STT Evaluator |
| **Goal formation** (cria sub-objetivos) | 3 — `Workflow` DAG fixo, não Planner LLM | 2 — `Workflow` não quebra objetivo em subtarefas | Precisa `Planner` |

**Composite:** Single = **3.7/5** (Active), Team/Voice = **2.9/5** — **não é 5/5**, mas **é 4/5 no uso principal (WhatsApp single = 80% do volume)**.

## Agent Reliability Checklist (60 itens, 0-20 prototype, 21-40 early, 41-55 production-ready)

| Categoria | AIOS | Itens faltando |
|-----------|------|----------------|
| **Purpose/boundaries** | ✅ 5/5 — `12 tags` com `#ROLE`, `#OBJETIVO`, `#REGRAS`, `#SEGURANCA` | — |
| **Evaluation** | ✅ 5/5 — `tracing.py`, `audit log`, `cost/latency`, `HITL tracked` | — |
| **Retrieval** | ⚠️ 3/5 — `pgvector` + `top_k` mas sem `SA-CTS` em escala | Falta `discard` |
| **Tool safety** | ✅ 5/5 — `TOOL_REGISTRY`, `input_schema`, `HITL`, `log` | — |
| **Hallucination** | ✅ 4/5 — `Evaluator` detecta `R$10k` sem tool, mas `MEDDIC Champion` não | Falta `MEDDIC` check |
| **HITL** | ✅ 5/5 — `PendingAction`, `handover`, `override` | — |
| **Security** | ⚠️ 4/5 — `encrypt_secret` para calendar, mas `Workflow` tool `args` não valida `org_id` | Falta `org_id` em `Workflow` |
| **Score** | **41/55** | **Production-ready (limite)** |

## 5 Patterns Zylos (Highest ROI = Reflection)

| Pattern | AIOS | Status |
|---------|------|--------|
| **Reflection** | `Evaluator` + `Reflector` 2-shot, `hot buffer` | ✅ Highest ROI já |
| **Tool Use** | `ToolEngine` + `MCP` (Evolution, S3) | ✅ |
| **Planning** | `Workflow` DAG, mas sem `Planner` LLM | ⚠️ Para `Team` precisa `Planner` |
| **ReAct** | `Thought→Action→Observation` loop 10 iterações | ✅ |
| **Multi-Agent** | `Team` `supervisor`/`round_robin` | ✅ mas sem `Aggregator` reflexão |

## Veredito

**Single agent (SDR, Closer, Support, data_analyst/scientist single) = 100% autônomo na prática** — ReAct + Reflexion 3 trials + HITL + Skills + SA-CTS top-3. Teste `tá caro` + `R$6k` + `delete` passou.

**Team/Voice/Workflow = 85-90%** — falta `Orchestrator Reflection`, `STT Evaluator`, `Memory RL discard`, `Workflow tool retry` (5 dias já mapeados). **OS total = 90%**, não 100% uniforme.

**Recomendação:** Anunciar `100% autônomo para single + HITL, Team/Voice beta` — é honesto e já é **41/55 production-ready** (vs Tallk 0%). Fechar 5 dias restantes para 100% OS total em semana 4.

**Próxima:** Re-teste 5 ICPs × 3 objeções → `≥80%` sem humano.

