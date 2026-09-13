# Reunião Comercial × SWE — CRM IA: Melhorias que Fazem Sentido

**Data:** 2026-09-13 15:00 — 16:00 (60min)  
**Local:** Sala Comercial + Meet  
**Facilitador:** PMM  
**Participantes:**

| Time | Quem | Foco |
|------|------|------|
| **Comercial** | Head Vendas + 2 AEs (Felipe, Patrícia proxies) + CS (Roberto proxy) | Fechar, pipeline, churn, ticket |
| **SWE** | SWE Lead (8a), SWE Jr (2a), Arquiteto | Viabilidade, custo, débito |

**Objetivo:** Listar melhorias no **CRM IA** (kanban + `crm_create_deal`/`crm_update_deal` + `HITL`) que **fazem sentido** serem feitas — i.e., que **Comercial fecha mais** E **SWE consegue entregar sem virar Salesforce**.

**Input:** CRM hoje: `CrmDeal` (kanban `prospection→closed_won/lost`, `value`, `score`, `source=whatsapp`), `CrmDealVersion` (audit trail, recém), `HITL >R$5k/≥10%` + `deduplicação` + `lock` (recém). Home: `CRM 100% automatizado por agentes IA — Kanban sem planilha` (website).

---

## 1. Comercial — O que dói e faz perder venda (15min)

**Head Vendas:** "Vou ser direto. Hoje o CRM IA é **'cria deal e move stage'** — é um **kanban bonitinho**, mas não é CRM. Perdemos para **Pipedrive (R$5,9k/ano)** e **HubSpot (R$12k/ano)** por 3 motivos:

1.  **Patrícia (franquia 12 unidades, 200 leads/mês):** 'Crio 200 deals via `crm_create_deal`, mas não consigo **filtrar por unidade** (`pipeline`), **ordenar por `value`**, ou **exportar CSV** para o contador. Tenho que abrir cada card.'
2.  **Felipe (franquia 48k, 200 unidades):** 'Preciso de **relatório `mql→closed_won` por unidade** para pagar bônus. Hoje tenho que fazer `sql_query` manual. Quero **dashboard** no CRM, não no Grafana.'
3.  **Roberto (clínica, 8 func, SDR+Closer):** 'Meu SDR cria deal, meu Closer move para `closed_won`, mas **não vejo quem criou** (`changed_by`) nem **histórico de `value` 5000→6000**. Preciso para **BAA** (auditoria).'
4.  **AE Felipe (proxy):** 'Perdemos `R$60k` Enterprise porque **não tem `score` → `stage` automático**. SDR qualifica `lead_score 85` mas tem que mover manualmente para `sql`. Queria **automação**: `score ≥70 → mql`, `≥85 → sql`.'"

**CS (Roberto proxy):** "E **follow-up**: 30% dos deals ficam em `mql` 7 dias sem mover. Hoje ninguém avisa. Precisa **alerta `mql >7d` → push WhatsApp** para o dono."

**Head Vendas:** "Se CRM fosse só kanban, não pagariam `R$249`. Precisa **fechar loop**: `lead → score → stage → alerta → relatório → comissão`."

---

## 2. SWE — O que é viável sem virar Salesforce (15min)

**SWE Lead:** "Entendo as dores. Mas preciso proteger vocês de **over-engineering**. CRM IA não precisa ser **Salesforce** (500 features). Precisa ser **kanban que fecha loop com IA**. Vou classificar cada pedido em **P0 (semana), P1 (semana 3), NÃO (pós-PMF)**.

**Critério SWE:** `Esforço` × `Impacto Comercial` × `Risco de virar planilha complexa`. Se `Esforço >2 dias e Impacto <20% conversão`, é **NÃO**."

**Arquiteto:** "E **custo de manter**. Cada filtro, export, dashboard é **dívida**. Prefiro **3 melhorias que fecham loop** do que 10 que viram `Jira` para CRM."

**SWE Jr:** "Posso fazer **filtros + ordenação + export CSV** em 1 dia (é `SELECT where pipeline/order by value` + `COPY TO CSV`). Mas **dashboard de conversão por unidade** é **BI** — 3 dias com `Recharts` ou `Grafana embed`. Precisa priorizar."

---

## 3. Discussão — Ideias e Priorização (20min)

| # | Ideia Comercial | Por que faz sentido (Comercial) | Por que faz sentido (SWE) | P0/P1/NÃO | Decisão |
|---|-----------------|----------------------------------|---------------------------|-----------|---------|
| **C1** | **Filtro `pipeline` + ordenação `value` + busca `lead_email`** no kanban | Patrícia filtra 200 deals por unidade, ordena por valor para priorizar | **1 dia**, `SELECT where pipeline` + `order by value desc` + `ilike` — já tem `pipeline` col em `CrmDeal` | **P0** | **SIM — semana** |
| **C2** | **Export CSV 1-click** no kanban | Contador pede CSV, hoje tem que `sql_query` | **0,5 dia**, `COPY (SELECT ...) TO CSV` + `StreamingResponse` | **P0** | **SIM** |
| **C3** | **Score → stage automático**: `lead_score ≥70 → mql`, `≥85 → sql`, `<50 → closed_lost` | AE Felipe perde 15min/dia movendo manual; automação fecha loop `lead → score → stage` sem humano | **0,5 dia**, `if score>=85: stage=sql` no `CRMTool.run` após `lead_score` | **P0** | **SIM — faz junto com C1** |
| **C4** | **Alerta `mql >7d` sem mover → push WhatsApp** para dono | CS: 30% deals apodrecem em `mql`; alerta proativo salva | **1 dia**, `cron` diário `SELECT where stage=mql and updated_at < now-7d` + `enqueue_job` `send WhatsApp` | **P1** | **SIM — semana 3** |
| **C5** | **Dashboard `mql→closed_won` por `pipeline` (unidade) para bônus** | Felipe precisa pagar bônus por unidade, hoje faz `sql_query` manual | **2,5 dias**, `Recharts` Bar + `GROUP BY pipeline, stage` + `conversion %` — é **BI**, não CRM | **P1** | **NÃO agora** → usar `Grafana` já tem (`otel`) + `sql_query` até pós-PMF |
| **C6** | **Histórico `value` 5000→6000 + `changed_by`** no card | Roberto precisa para `BAA` (auditoria) | **0 dias** — **já feito** em `CrmDealVersion` (recém) — só mostrar no UI | **P0** | **SIM — só UI** |
| **C7** | **Comentários no deal** (`notes` com `@menção`) | SDR deixa `notes: "cliente pediu desconto 12%"` e Closer vê | **0,5 dia**, `extra_data.notes` já existe, só UI `textarea` + `append` | **P0** | **SIM** |
| **C8** | **Merge de deals duplicados** (mesmo `lead_email`) | Patrícia cria 2 deals mesmo email por engano, hoje `dedup` só bloqueia se `stage` not closed — mas se `closed_lost`, deveria permitir novo | **0,5 dia**, `dedup` já faz, só ajustar `where stage not in (closed_won, closed_lost)` → já está | **Feito** | — |
| **C9** | **Campos custom por `pipeline`** (ex: franquia tem `unidade`, clínica tem `convênio`) | Comercial quer vender para nichos com campos diferentes | **NÃO** — vira `Salesforce` + `500 colunas` + inferno de `migrate` | **NÃO** | — |
| **C10** | **Previsão `close date` + `probabilidade` por `score`** | AE quer `forecast` | **NÃO** — é `Data Scientist` `feature store`, não CRM kanban | **NÃO** | — |

**Debate quente:**

**Comercial:** "C5 dashboard por unidade é P0 para Felipe — ele não fecha `R$60k` sem isso. Por que é NÃO?"

**SWE Lead:** "Porque `Grafana` já tem `otel` + `pgvector` + `UsageRecord`. Posso fazer `SELECT pipeline, stage, count(*), avg(value) GROUP BY` em 2 linhas e jogar no Grafana em 1h. Fazer **BI dentro do kanban** é 2,5 dias de `Recharts` + `design` + `teste`. Para **1 cliente Enterprise** (Felipe), não vale atrasar GA para 10 orgs beta. **Solução:** Eu faço **query pronta** para Felipe (`SELECT pipeline, stage, count(*)...`) e **treino CS** a rodar `sql_query` no `Analyst` — resolve em 1h, sem código.

**Comercial:** "Topo. Mas se Felipe pagar `R$60k`, aí faz dashboard?"

**SWE Lead:** "Sim, pós-assinatura, com `BAA` + `Enterprise` 500 agentes — aí vira P0."

**Arquiteto:** "E `C9` campos custom? Se fizer, vira `Salesforce` e nunca mais sai. Melhor manter `extra_data` JSON flexível — cada `pipeline` guarda o que quiser em `extra_data`, sem coluna nova. É `NoSQL` dentro de `Postgres` — já é robusto sem virar `500 colunas`."

**Comercial:** "Topo. `extra_data` já resolve para nicho."

---

## 4. Decisão Final — O que faz sentido (votação 5/5)

**SWE Lead propõe, Comercial aprova:**

**P0 (esta semana, 2,5 dias) — fecha loop `lead → score → stage → histórico` sem virar Salesforce:**

| # | O que | Owner | Dia |
|---|-------|-------|-----|
| C1 | Filtro `pipeline` + busca `lead_email` + ordenação `value` no kanban | SWE Jr | 1d |
| C2 | Export CSV 1-click | SWE Jr | 0,5d |
| C3 | Score → stage automático (`≥70 mql, ≥85 sql`) | SWE Lead | 0,5d |
| C6 | Mostrar `CrmDealVersion` histórico no card (quem, quando, `value`) | SWE Jr | 0,5d |
| C7 | Comentários `notes` com `append` no card | SWE Jr | 0,5d |

**Total P0: 3 dias → GA `2026-09-17` mantido.**

**P1 (semana 3, 1 dia):**

| # | O que | Owner |
|---|-------|-------|
| C4 | Alerta `mql >7d` → push WhatsApp (cron + Evolution) | SWE Lead |

**NÃO (pós-PMF, com `BAA` + `Enterprise`):**

| # | Por que NÃO agora |
|---|-------------------|
| C5 Dashboard por unidade | Usa `Grafana` + `sql_query` até ter 3 Enterprises pedindo |
| C9 Campos custom por pipeline | Usa `extra_data` JSON flexível, não coluna |
| C10 Forecast `close date` | É `Data Scientist`, não kanban |

**Métrica de saída P0 (2026-09-17):** Patrícia filtra 200 deals por `pipeline` em <10s + exporta CSV em 1 clique + SDR não move manual `mql→sql` (score faz) + Roberto vê histórico `5000→6000` no card.

**Risco aceito:** Felipe sem dashboard por unidade até ter `BAA` — usará `Grafana` + `sql_query` com treinamento CS.

---

**Assinaturas:**

Comercial Head: _________________  SWE Lead: _________________  Arquiteto: _________________  Data: 2026-09-13

**Próxima:** 2026-09-17 — Demo P0 para Patrícia/Felipe

