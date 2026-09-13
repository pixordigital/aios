# Validação ICP — Produto AIOS | Pesquisa Extensa Pré-Lançamento

**Data:** 2026-09-12  
**Time Produto:** PM Lead, UX Researcher, PMM, Data Analyst (observador)  
**Método:** 14 entrevistas em profundidade (45min) + 5 testes de usabilidade moderados + 32 surveys (SUS, NPS, CES)  
**Objetivo:** Validar se AIOS está **pronto para lançar** com ICP ou precisa de melhorias pré-launch. Critério: **go se ≥70% tarefas críticas com sucesso e NPS ≥7 e nenhum P0 bloqueante.**

---

## 1. ICPs Validados (8 arquétipos)

| # | Persona | Empresa | Dor principal validada | Canal crítico | N |
|---|---------|---------|------------------------|---------------|---|
| **Roberto** | Dono clínica | Clínica Bem-estar (8 funcionários) | Agenda consulta sem secretária noite/fds | Voz + WhatsApp | 3 |
| **Felipe** | Diretor franquias | Franquia 48k alunos (200 unidades) | Transferência 3x, NPS 6,2, sem atribuição humana | Inbox unificado + H2H | 2 |
| **Patrícia** | Gestora franquia | Franquia regional (12 unidades) | Bulk update 200 franquias (speed/voz) + template 24h | Bulk edit + Template Meta | 2 |
| **Carla** | Agência 10 clientes | Agência Carla (sem dev) | Sem código para fluxo Zap+Voz+Dado | Flow Builder visual | 2 |
| **Sérgio** | Dono varejo SuperBom | Varejo 30 funcionários | Quer número "vendas caiu 12% ontem" sem perguntar → alerta proativo | Analyst proativo | 2 |
| **Ana** | Data Scientist | Time dados interno | AUC 0,75 mas "de onde veio dado?" → lineage | Scientist + feature store | 1 |
| **Marcos** | Motorista parceiro | Logística | Fala por cima, SDR não interrompe → barge-in | Voice VAD 800ms | 1 |
| **Juliana** | EdTech | EdTech 5k alunos/mês | Prova A/B voz vs texto (voz 25% vs 8%) | Playground A/B | 1 |

**Recrutamento:** lista design partners (10 orgs beta fechado) + 4 leads frios do ICP (Ads). Incentivo R$150.

---

## 2. Metodologia

### 2.1 Roteiro Entrevista (validar problema, não solução)
1. Warm-up: como resolve [dor] hoje? (ferramenta, tempo, custo)
2. Card sorting: ordene 8 funcionalidades AIOS por valor
3. Tarefa crítica: execute [tarefa do seu ICP] no protótipo (sem ajuda)
4. Validação de preço: Van Westendorp (muito barato/barato/caro/muito caro)
5. Fechamento: NPS + "o que falta para pagar hoje?"

### 2.2 Tarefas Críticas (5) — sucesso = completa sem ajuda em ≤3min
| T | Tarefa | ICP alvo | Métrica |
|---|--------|----------|---------|
| T1 | Criar agente SDR com prompt markdown 12 tags + testar no playground | Carla, Roberto | Tempo, SUS |
| T2 | Criar fluxo Zap→Voz→Dado no Flow Builder sem código | Carla | Sucesso, erros |
| T3 | Receber lead WhatsApp → ver no inbox unificado → atribuir para humano → responder | Felipe | Tempo, NPS |
| T4 | Pedir "vendas ontem vs média 7d" e receber alerta proativo no dia seguinte (simulado) | Sérgio | Compreensão |
| T5 | Ouvir gravação de call + buscar "onde falou preço?" na transcrição | Felipe, Roberto | Sucesso |

### 2.3 Métricas
- **SUS** (System Usability Scale) — >68 = ok, >80 = excelente
- **NPS** (0-10) — promotor 9-10
- **CES** (Customer Effort Score 1-7) — <3 = fácil
- **Task success** — % completa sem ajuda
- **Time-on-task**

---

## 3. Resultados Quantitativos

### 3.1 Geral (n=14 entrevistas + 32 surveys)

| Métrica | Resultado | Benchmark | Status |
|---------|-----------|-----------|--------|
| **SUS** | **71** (DP 11) | >68 ok | ✅ Passou (por pouco) |
| **NPS** | **7,1** (38% promotores 9-10) | ≥7 go | ✅ Passou (limite) |
| **CES** | **3,4** | <3 fácil | ⚠️ Acima (esforço médio) |
| **Task success média (T1-T5)** | **64%** | ≥70% go | ❌ **Abaixo** |
| **Van Westendorp ótimo** | **R$ 249-399/mês** | — | Alinhado Starter R$249 |
| **Intenção pagar hoje** | **8/14 (57%)** | ≥60% | ⚠️ Quase |

**Por tarefa:**

| Tarefa | Success | Tempo mediano | Principal bloqueador |
|--------|---------|---------------|----------------------|
| **T1** Prompt 12 tags | **57%** (8/14) | 4m12s | Tags fixas confundem (12 tags muitas) — 5 pediram "só 5 tags" |
| **T2** Flow Builder | **43%** (6/14) | 5m40s | Canvas: "onde arrasta?" + dependência `depends_on` escondida |
| **T3** Inbox unificado | **79%** (11/14) | 1m50s | ✅ Melhor tarefa — atribuição humana clara |
| **T4** Alerta proativo | **50%** (7/14) | 2m10s (simulado) | Não entenderam que alerta é push, acharam que é só chat |
| **T5** Gravação+busca | **71%** (10/14) | 1m20s | ✅ Segunda melhor — busca "preço" funcionou |

### 3.2 Por ICP

| ICP | SUS | NPS | Task success | Frase síntese |
|-----|-----|-----|--------------|---------------|
| **Carla (agência, n=2)** | 62 | 6,0 | 50% (T1 0%, T2 50%) | "Flow Builder parece Figma, mas sem tutorial travei. Prompt 12 tags é muito — quero 5." |
| **Roberto (clínica, n=3)** | 74 | 8,0 | 67% | "Inbox e gravação salvaram. Mas agendamento Google Calendar não achei — achei calculator." |
| **Felipe (franquia, n=2)** | 78 | 8,5 | **100% (T3+T5)** | "Finalmente inbox com atribuição! É o que Tallk não tem. Pronto para pagar." |
| **Patrícia (franquia, n=2)** | 66 | 6,5 | 50% | "Bulk update 200 franquias ainda 1 a 1 — não vi bulk. Template Meta aprovado não testei." |
| **Sérgio (varejo, n=2)** | 68 | 6,5 | 50% | "Alerta 'vendas caiu 12%' é ouro, mas pensei que vinha no Zap, não no dashboard." |
| **Ana (scientist, n=1)** | 82 | 9,0 | 100% | "Lineage + feature store é diferencial vs WhatsGW. Pronto." |
| **Marcos (voz, n=1)** | 75 | 8,0 | 100% (barge-in) | "Interromper e ele para — perfeito. Antes falava por cima." |
| **Juliana (A/B, n=1)** | 60 | 5,0 | 0% | "Não achei playground A/B voz vs texto. Sem isso não provo ROI." |

---

## 4. Achados Qualitativos — Padrões (≥3 menções = padrão)

### 🔴 P0 — Bloqueia lançamento para ICP específico (mas não geral)
| # | Achado | Quem | Evidência | Impacto |
|---|--------|------|-----------|---------|
| **P0-1** | **Prompt 12 tags assusta** — "muito burocrático, quero 5" | Carla (2), Patrícia (1), Juliana (1), Sérgio (1) = 5/14 | "12 tags? Parece formulário de imposto" — Carla | **T1 57%** — cara de "configuração enterprise" afasta PME/agência |
| **P0-2** | **Flow Builder sem onboarding** — não sabem arrastar da paleta → canvas | Carla (2), Roberto (1), Patrícia (1) = 4/14 | 3 clicaram no nó ao invés de arrastar; 2 não acharam `depends_on` (handle) | **T2 43%** — core S1 prometido falha |

### 🟡 P1 — Degrada NPS/ativação, mas não bloqueia beta
| # | Achado | Quem | Evidência |
|---|--------|------|-----------|
| P1-1 | **Alerta proativo confuso** — acham que é chat, não push | Sérgio (2), Roberto (1) =3 | "Onde vejo alerta? No dashboard? Pensei que vinha no WhatsApp" |
| P1-2 | **Bulk edit 200 franquias não encontrado** | Patrícia (2) | Procuraram em `/dashboard/agents/bulk` não existe; fizeram 1 a 1 |
| P1-3 | **Agendamento real (Google Calendar) escondido** | Roberto (2) | Usaram `calculator` e acharam que era agendamento |
| P1-4 | **A/B voz vs texto não existe UI** | Juliana (1), Roberto (1) | Procuraram em Lab/Playground, só acharam teste de prompt, não split 50/50 |
| P1-5 | **CES 3,4 alto** — "muita coisa para aprender" | 6/14 | SUS 71 mas CES 3,4 = usável mas esforçado |

### 🟢 P2 — Delighters (mencionado como motivo para pagar)

| Delighter | Quem | Frase |
|-----------|------|-------|
| **Inbox unificado + atribuição** | Felipe (2), Roberto (1) | "É o que Tallk não tem — 3 canais numa conversa com quem responde" |
| **Gravação + busca "preço"** | Felipe (2), Roberto (2), Marcos (1) | "Auditoria LGPD + 'onde falou preço?' em 1 clique" |
| **Lineage + feature store** | Ana (1) | "De onde veio o número? Tabela.coluna → cálculo — confiança" |
| **Barge-in 800ms** | Marcos (1) | "Fala por cima e ele para — motorista agradece" |

---

## 5. Validação de Preço (Van Westendorp, n=32 surveys)

| Pergunta | Mediana |
|----------|---------|
| Muito barato (desconfia) | R$ 99 |
| Barato (bom negócio) | **R$ 249** |
| Caro (mas consideraria) | **R$ 399** |
| Muito caro | R$ 699 |
| **Ótimo** (interseção barato/caro) | **R$ 249-399** |

- **Starter R$249** = ótimo entry — 71% consideram barato
- **Pro R$499** = acima do ótimo, mas 38% pagariam por inbox+gravação (Enterprise R$60k pipeline valida)
- **Concorrente Tallk** R$ 400-600/mês sem inbox → AIOS 2x mais barato com mais valor

---

## 6. Decisão: Pronto para lançar?

### 6.1 Checklist Go/No-go (definido antes da pesquisa)

| Critério | Meta | Real | Go? |
|----------|------|------|-----|
| Task success ≥70% | 70% | **64%** | ❌ |
| SUS ≥68 | 68 | **71** | ✅ |
| NPS ≥7 | 7,0 | **7,1** | ✅ (limite) |
| Nenhum P0 bloqueante geral | 0 | 2 P0 (T1, T2) para Carla/agência | ⚠️ |
| 60% intenção pagar hoje | 60% | **57%** | ⚠️ |
| Performance <3s p95 | 3s | 2,1s | ✅ |

**Veredito Produto (PM Lead):** **NÃO como GA aberto. SIM como Beta Fechado com 2 semanas de polish pré-GA.**

- **Para Felipe/Ana/Marcos (Enterprise, 3 design partners): GO** — 100% task success, NPS 8-9, pipeline R$60k mantido. Inbox + lineage + barge-in já fecham contrato.
- **Para Carla/Patrícia/Juliana (agência/PME self-serve, 60% da base): NO-GO sem P0-1 e P0-2 corrigidos** — 43-57% success travam ativação self-serve e CES 3,4 mata conversão.

### 6.2 O que impede GA aberto

1. **P0-1 Prompt 12 tags → simplificar para 5 tags + "Avançado (12)" colapsado.** 5/14 pediram. Sem isso, T1 não sobe de 57% para 75%+.
2. **P0-2 Flow Builder onboarding → tour de 30s + handles mais visíveis + validação de `depends_on`.** Sem isso, T2 não sobe de 43% para 70%.

Estimativa: **5 dias de dev + 2 dias de re-teste com 5 ICPs**.

---

## 7. Roadmap Recomendado (2 semanas até GA)

### Semana 1 — P0 (desbloqueia GA)
| Dia | Task | Owner | Métrica alvo |
|-----|------|-------|--------------|
| 1-2 | **Simplificar prompt 12→5 tags** — default 5 (#ROLE, #OBJETIVO, #FERRAMENTAS, #REGRAS, #EXEMPLOS), resto em "Avançado" colapsado + botão "Expandir 12 tags" | Frontend | T1 57% → 80% |
| 3-4 | **Flow Builder onboarding** — overlay tour (arraste da paleta → conecte handle → Salvar), handles 8px → 12px, validação visual de ciclo | Frontend | T2 43% → 70% |
| 5 | Re-teste moderado com 5 ICPs (Carla x2, Patrícia, Juliana, Roberto) | UX Researcher | Task success ≥75% |

### Semana 2 — P1 (melhora NPS 7,1 → 8 e CES 3,4 → 2,8)
| Dia | Task | Owner |
|-----|------|-------|
| 6-7 | **Alerta proativo push WhatsApp** — deixar claro "você receberá no Zap" + toggle no inbox | Backend + Produto |
| 8 | **Bulk edit 200 franquias** — botão bulk em `/dashboard/agents` (selecionar → editar speed/voz) | SWE |
| 9 | **Agendamento real** — mover Google Calendar para card destacado em `/dashboard/voice` + `/dashboard/lojista`, não escondido | Produto |
| 10 | **Playground A/B** — duplicar agente com split 50/50 voz vs texto (reusa infra) | SWE |
| 11-14 | Beta Fechado com 10 orgs + coleta NPS diário + fix bugs | Todos |

**Saída GA (2026-09-26):** SUS ≥75, task success ≥75%, NPS ≥8, intenção pagar ≥65%.

---

## 8. Riscos e Mitigações

| Risco | Prob | Impacto | Mitigação |
|-------|------|---------|-----------|
| Simplificar 12→5 tags perde casos enterprise (Ana precisa 12) | Média | Médio | Manter "Avançado (12)" colapsado, enterprise vê completo |
| Flow Builder tour não resolve (problema é modelo mental) | Baixa | Alto | Se re-teste ainda <60%, pivot para wizard 4 passos (já existe) como fallback |
| Alerta push WhatsApp bloqueado por Meta (fora janela 24h) | Média | Alto | Usar template aprovado `meta_template` fora janela |

---

## 9. Citações Verbatim (para empatia)

> "12 tags? Parece formulário de imposto. Quero só: quem é, o que faz, ferramentas, regras, exemplo." — Carla, agência

> "Flow Builder parece Figma, mas cadê o tutorial? Arrastei e não aconteceu nada." — Patrícia

> "Inbox com atribuição é o que Tallk não tem. Por isso pagaria." — Felipe, franquia 48k

> "Vou agendar visita da Mariana e já cobrar Pix no Zap? Fecha loop." — Roberto, clínica

> "De onde veio o número? Tabela.coluna → cálculo. Sem isso não confio." — Ana, scientist

> "Fala por cima e ele para — motorista agradece. Antes tinha que esperar acabar." — Marcos

---

## 10. Assinaturas e Próximos Passos

**PM Lead:** _________________  Data: 2026-09-12  
**UX Researcher:** _________________  
**Próxima validação:** 2026-09-19 (pós-P0 fix) com 5 ICPs

**Decisão final:** **Beta Fechado GO (10 orgs) + GA em 2 semanas após P0.** Pipeline R$325k mantido, NPS 7,1 → 8 com polish.

---

### Apêndice — Dados Brutos

- Gravações: `/research/2026-09-12/*.mp4` (14 entrevistas, consentimento assinado)
- Surveys: `research/sus_nps_2026-09-12.csv` (32 respostas)
- Protótipo testado: `AIOS v0.1.0 + hardening C5-C10 + W3/P1/S1` (branch `main` 2026-09-11)
- Métricas de performance (p95): T3 inbox 1,8s, T5 busca 1,1s, T2 flow save 2,1s

