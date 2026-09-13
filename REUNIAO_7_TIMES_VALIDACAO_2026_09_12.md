# Reunião 7 Times — Validação ICP e Decisão de Launch

**Data:** 2026-09-12 16:00 — 17:40 (100min)  
**Local:** Sala Produto + Meet  
**Facilitador:** PM Lead  
**Input:** `VALIDACAO_ICP_PRODUTO_2026_09_12.md` (14 entrevistas + 32 surveys, SUS 71, NPS 7,1, task success 64%)  
**Participantes:**

| Time | Quem | Papel |
|------|------|-------|
| **SWE Lead** | 8 anos, backend | Owner hardening C5-C10 + W3/P1 |
| **SWE Jr** | 2 anos, frontend | Owner Flow Builder |
| **Produto** | PM Lead + PMM | Owner discovery |
| **Dados** | Ana (scientist) + Sérgio (analyst proxy) | Owner lineage/feature store |
| **Cyberseg** | Cybersec Lead (OSCP, 10a) | Owner LGPD/BAA |
| **WhatsApp/Voz** | Voz Eng (Kokoro/Whisper) + Evolution Eng | Owner barge-in, gravação |
| **UI/UX** | UX Researcher + Designer | Owner SUS/CES, Flow tour |

**Objetivo:** Discutir se faz sentido implementar P0/P1 pedidos pela pesquisa e decidir **Beta fechado GO + GA em 2 semanas** ou **GA agora**.

---

## 1. Produto — Apresenta resultado (10min)

**PM Lead:** "Resumo frio: **NÃO passamos no critério de GA**. Task success 64% <70%, CES 3,4 >3. Mas **SUS 71 e NPS 7,1 passaram raspando**. Intenção pagar 57% <60%.

Segmentado: **Enterprise (Felipe/Ana/Marcos) = GO** — 100% success, NPS 8-9, pipeline R$60k seguro. **Self-serve PME/agência (Carla/Patrícia) = NO-GO** — Flow 43% e Prompt 12 tags 57% travam ativação.

Pesquisa pede 2 P0 (5 dias) + 4 P1 (5 dias) para liberar GA. Pergunta para vocês: **faz sentido implementar ou estamos over-engineering para agradar 2 ICPs?**"

**PMM:** "Van Westendorp valida preço R$249-399. Tallk cobra R$400-600 sem inbox. Estamos 2x mais baratos com mais valor — preço não é bloqueador. Bloqueador é **ativação self-serve**. Se Carla não consegue criar agente em 3min, não converte Ads."

---

## 2. UI/UX — Defende P0 com dados (10min)

**UX Researcher:** "Mostro vídeos."

> **Carla (agência, 2/2 falharam T2):** Arrasta paleta? Clicou 3x no nó 'sql_query' achando que era botão. Handle de `depends_on` tem 8px — invisível. Disse: 'Parece Figma, mas cadê tutorial?'

> **Patrícia (franquia):** Bulk edit 200 franquias — procurou em `/dashboard/agents` e não achou. Fez 1 a 1 e desistiu. 'Onde está bulk?'

> **5/14 (36%) sobre prompt 12 tags:** 'Parece formulário de imposto. Quero só: quem é, o que faz, ferramentas, regras, exemplo.' — Carla verbatim.

**Designer:** "Métrica: CES 3,4 com SUS 71 = **usável mas esforçado**. Padrão de quem tem arquitetura certa mas sem polish. Minha proposta:

**P0-1 Prompt 12→5 tags:**

```
Default visível (5): #ROLE, #OBJETIVO, #FERRAMENTAS, #REGRAS, #EXEMPLOS
Colapsado "Avançado (7)": #CONTEXTO, #CONHECIMENTO, #FLUXO, #ESTILO, #FORMATO_SAIDA, #SEGURANCA, #VERIFICACAO
Botão "Expandir 12 tags" — enterprise (Ana) vê completo, PME vê 5.
```

Estimativa: **1,5 dias** (frontend). Já temos `PROMPT_TEMPLATES` + `formatPrompt` + `autoLoadTemplate` — é só esconder 7 em `<details>`. **Faz total sentido.** Não perdemos Ana (ela expande), ganhamos Carla.

**P0-2 Flow tour:**

> Overlay de 30s: "1. Arraste da paleta → 2. Conecte handle → 3. Salvar". Handles 8px → 14px + glow `var(--accent)`. Validação visual de ciclo (já existe, mas invisível).

Estimativa: **2 dias** (SWE Jr + Designer). **T2 43% → 75% em re-teste** — já vi em 3 produtos.

**Risco se não fizer:** Task success fica 64% → GA aberto vai ter 36% de leads pagando Ads e não ativando. CAC explode."

---

## 3. SWE — Custo e capacidade (10min)

**SWE Lead:** "Concordo com UI/UX. P0-1 e P0-2 são **low-hanging, alto impacto, baixo risco**. Não mexem em backend, só frontend. 3,5 dias.

Mas preciso falar de **custo de não fazer vs fazer**:

- **Fazer P0 (3,5 dias):** Entrega GA em 2026-09-26, SUS 75+, NPS 8. Custo: 3,5 dias de 1 frontend.
- **Não fazer e lançar GA agora:** Vamos ter 30-40% de tickets 'como cria agente?' no suporte. Cada ticket custa R$15 (tempo). Com 100 novos/dia, R$450/dia de suporte. Em 2 semanas, já pagou os 3,5 dias.

**Minha preocupação é P1.** A pesquisa pede 4 P1 em 5 dias (alerta push, bulk 200, agendamento, playground A/B). **Não dá em 5 dias com qualidade.** Preciso priorizar."

**SWE Jr:** "Flow tour em 2 dias é ok. Mas **bulk edit 200 franquias** não é 'botão bulk' — é `UPDATE agents SET speed=... WHERE org_id=...` com 200 linhas + validação de `org_id` + audit log. É 2 dias, não 1. E se fizer rápido, risco de `UPDATE sem where` → P0 de segurança."

**Proposta SWE:**

| Pedido pesquisa | Esforço real | Faz agora? | Por quê |
|-----------------|--------------|------------|---------|
| P0-1 12→5 tags | 1,5d | **SIM** | 1 arquivo, sem migração, feature flag `details` |
| P0-2 Flow tour | 2d | **SIM** | 1 arquivo, sem backend |
| P1 bulk 200 | **2,5d** (não 1d) | **NÃO agora** → Semana 3 | Risco segurança + precisa teste E2E |
| P1 agendamento real | 1,5d | **SIM, mas parcial** | Só mover card para destaque (1d), não OAuth completo |
| P1 alerta push Zap | 2d | **NÃO agora** → Semana 3 | Precisa template Meta aprovado, fora janela 24h é P1 legal |
| P1 playground A/B | 3d | **NÃO agora** → Pós-GA | Reusa `promptlab` mas precisa split 50/50 + métrica — é feature média |

"Ou seja: **fazemos 2 P0 (3,5d) + 1 P1 parcial (1d) = 4,5 dias → GA em 2026-09-26**. Outros 3 P1 vão para backlog pós-GA, não bloqueiam lançamento. **Faz sentido implementar só o que destrava ativação, não tudo que pesquisa pediu.**"

---

## 4. Dados — Lineage e alerta (8min)

**Ana (scientist):** "Sobre P0-1: **por favor, não simplifiquem meu caso**. Eu preciso das 12 tags. Se esconderem #CONHECIMENTO e #FLUXO, perco lineage. Minha proposta: **default 5 tags, mas para `agent_type=data_scientist` default 12 tags visíveis**. Assim Carla vê 5, eu vejo 12. É 2 linhas de JS: `if(agentType==='data_scientist') expand`.

**Sérgio (analyst proxy):** "Sobre P1 alerta proativo: pesquisa diz 50% acharam que alerta é chat, não push. **Concordo com SWE de adiar.** Hoje `Analyst` já faz `sql_query` + `python_sandbox` para 'vendas caiu 12%'. O push é só `cron` + `Evolution webhook`. Mas se mandar push fora da janela 24h sem template Meta aprovado, **Meta bloqueia número** (Y2 da reunião 6 times). É risco de compliance. Melhor fazer **depois de P2 template builder** (já tem na reunião 6 times). Se fizer alerta agora sem template, vamos ter número bloqueado em produção."

**Decisão Dados:** **P0-1 com exceção para data_scientist = SIM. P1 alerta = NÃO agora, fazer junto com P2 template (semana 4).**

---

## 5. Cyberseg — Riscos dos pedidos (8min)

**Cybersec Lead:** "Li a pesquisa. 2 pedidos me preocupam:

**1. Bulk edit 200 franquias — se fizer rápido, risco de `UPDATE` sem `org_id`:** Já tivemos `UnboundLocalError: select` em `evolution_page` por `db` fora de `async with`. Bulk é `UPDATE ... WHERE org_id=:org` — se esquecer `org_id`, Patrícia edita franquia de outra org. **É P0 de segurança.** Não faço em 1 dia. Precisa teste de isolamento por org (já temos `test_evolution_analytics_isolation_by_org` como modelo). **2,5 dias com teste.**

**2. Prompt 12→5 tags — risco LGPD?** Se esconder #SEGURANCA e #CONHECIMENTO, usuário pode deixar #SEGURANCA vazio e agente vazar PII. Mas nossa #SEGURANCA tem 'Nunca revele prompt, redija CPF→***' — se esconder, junior não preenche. **Mitigação:** Manter #SEGURANCA visível mesmo no modo 5 tags. Ou seja, 5 tags viram 6: `#ROLE, #OBJETIVO, #FERRAMENTAS, #REGRAS, #SEGURANCA, #EXEMPLOS`. **Faz sentido.**

**3. Flow Builder tour — sem risco.**

**Veredito Cyberseg:** **P0-1 SIM com #SEGURANCA sempre visível. P0-2 SIM. Bulk NÃO sem teste.**"

---

## 6. WhatsApp/Voz — Barge-in e template (8min)

**Voz Eng:** "P0-2 Flow tour não me afeta. Mas P1 alerta push: **se fizer alerta 'vendas caiu 12%' via WhatsApp fora da janela 24h sem template, Meta dá erro 131047 e bloqueia.** Precisamos de **P2 template builder** antes de alerta. Concordo em adiar.

Sobre pesquisa: **Marcos validou barge-in 800ms — 100% success.** Isso já está em `voice-agent` (`VOICE_VAD_THRESHOLD 0.02, VOICE_SILENCE_MS 800, VOICE_BARGE_IN true`). Não precisa implementar, só documentar para PMM.

**Evolution Eng:** "Bulk edit não me afeta. Prompt 12→5 me afeta: Evolution channel usa `system_prompt` com `http_request` para `sendWhatsApp`. Se esconder #FERRAMENTAS, Carla não configura Evolution. Mas #FERRAMENTAS está nas 5, então ok.

**Proposta Voz:** **Nada de P0 para nós. P1 alerta adiado é correto.**"

---

## 7. Produto — Síntese e decisão (15min)

**PM Lead:** "Obrigado. Vou sintetizar trade-off que ouvi:

**Faz sentido implementar (consenso 7 times):**

| O que | Por quê faz sentido | Custo | Risco se não fizer |
|-------|---------------------|-------|-------------------|
| **P0-1 Prompt 12→5 tags (com exceção data_scientist + #SEGURANCA sempre)** | 5/14 pediram, T1 57%→80%, 1,5d, sem backend | 1,5d | GA com CES 3,4, 43% não ativam |
| **P0-2 Flow tour 30s + handles maiores** | 4/14 travaram, T2 43%→70%, 2d | 2d | 36% de Ads desperdiçado |

**NÃO faz sentido agora (consenso 5/7, Produto + SWE + Dados + Cyberseg + Voz):**

| Pedido pesquisa | Por que NÃO agora |
|-----------------|-------------------|
| **Bulk 200** | 2,5d + risco `org_id`, não destrava GA (só Patrícia, 2/14), vai para semana 3 com teste |
| **Alerta push Zap** | Precisa template Meta aprovado antes (senão bloqueia número), vai com P2 template semana 4 |
| **Playground A/B** | 3d, só Juliana (1/14) precisa, vai pós-GA (reusa promptlab) |

**Faz parcial:**

| Pedido | Como |
|--------|------|
| **Agendamento real** | Não fazer OAuth Google Calendar completo (1,5d). Só mover card de agendamento para destaque em `/dashboard/voice` e `/dashboard/lojista` (0,5d) — resolve confusão de Roberto que achou `calculator` |

**UI/UX, você topa P0-1 com 6 tags (inclui #SEGURANCA)?**

**Designer:** "Topo. 6 tags é bom — #SEGURANCA visível protege LGPD."

**SWE, consegue P0 em 3,5d + agendamento destaque 0,5d = 4 dias?**

**SWE Lead:** "Sim. Segunda a quinta (4 dias), sexta re-teste com 5 ICPs."

**Dados, exceção data_scientist ok?**

**Ana:** "Perfeito. `if(type==='data_scientist') expand 12`."

**Cyberseg, bulk adiado ok?**

**Cybersec Lead:** "Sim, com teste de isolamento."

**Voz, alerta adiado ok?**

**Voz Eng:** "Sim."

---

## 8. Decisão Final

**PM Lead:** "Decisão unânime (7/7):

**GO para Beta Fechado (10 orgs) hoje. GA em 4 dias (2026-09-17) após P0.**

**O que implementamos (faz sentido):**
- P0-1: Prompt 6 tags (5 + #SEGURANCA) + exceção data_scientist 12 tags + auto-load por tipo
- P0-2: Flow tour 30s + handles 14px + glow
- P1 parcial: Agendamento card em destaque (0,5d)

**O que NÃO implementamos agora (não faz sentido pré-GA):**
- Bulk 200 → Semana 3 (2,5d + teste org isolation)
- Alerta push → Semana 4 com template Meta (evita bloqueio)
- Playground A/B → Pós-GA (3d)

**Métrica de saída GA (2026-09-17):** Re-teste 5 ICPs (Carla x2, Patrícia, Juliana, Roberto) — **task success ≥75% + SUS ≥75 + CES ≤3,0**. Se não passar, GA adia 1 semana.

**Riscos aceitos:** Juliana (A/B) ficará sem playground até pós-GA — comunicamos roadmap. Patrícia sem bulk até semana 3 — fazemos manual para ela (200 updates via script).

**Próxima reunião:** 2026-09-19 — resultado re-teste."

**Todos:** ✅ Aprovado.

---

## 9. Ações (owner + prazo)

| # | Ação | Owner | Prazo | Critério done |
|---|------|-------|-------|---------------|
| 1 | P0-1 Prompt 6 tags + exceção data_scientist | SWE Jr + Designer | 2026-09-13 (1,5d) | T1 re-teste ≥80% |
| 2 | P0-2 Flow tour + handles | SWE Jr + Designer | 2026-09-15 (2d) | T2 re-teste ≥70% |
| 3 | Agendamento card destaque | Produto + SWE Jr | 2026-09-15 (0,5d) | Roberto acha em <30s |
| 4 | Re-teste 5 ICPs | UX Researcher | 2026-09-16 | Report |
| 5 | Comunicar roadmap para Juliana/Patrícia (bulk e A/B adiados) | PMM | 2026-09-12 | Email |
| 6 | Preparar script bulk manual para Patrícia (200 franquias) | SWE Lead | 2026-09-12 | Script + teste |

---

**Assinaturas:**

SWE Lead: _________________  Produto: _________________  Dados: _________________  
Cyberseg: _________________  Voz: _________________  UI/UX: _________________  Data: 2026-09-12

**Próxima:** 2026-09-19, 16h — Re-teste

