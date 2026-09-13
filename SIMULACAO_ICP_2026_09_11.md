# Simulação ICP — AIOS Voz & Dados Multi-canal

**Produto:** AIOS — `Voz (SDR/Closer/Suporte)` + `Dados (Analyst/Scientist)` • `Multi-canal nativo` (WhatsApp hero via Evolution API Cloud API) • `TTS Kokoro $0/min` • `STT Whisper self-hosted` • `SQL+python_sandbox` • PT-BR nativo `pm_alex` • Multi-tenant + white-label • Deploy 1-click Coolify

**Mesa:** PM Lead + 12 ICPs reais + Sales + Eng (observadores)

---

## Participantes (12 ICPs)

| # | Nome | Empresa | Porte | Segmento | Dor #1 | Orçamento atual |
|---|------|---------|-------|----------|--------|-----------------|
| 1 | Roberto | Clínica OdontoPrime | 12 func | Saúde | Leads perdidos 18h-8h, plantonista R$3,5k | R$3,5k/m |
| 2 | Mariana | VivaReal Imóveis | 45 corretores | Imobiliário | 2 SDRs R$18k, turnover 40%, follow-up falha | R$18k/m |
| 3 | Felipe | ModaFit E-commerce | 80 func | Varejo | Suporte 24/7 R$48k, NPS 6,2 | R$48k/m |
| 4 | Carla | GrowthLab Agência | 8 func | Marketing | 5 clientes pedem `IA no WhatsApp`, custo gringo R$15k setup | R$0 novo rev |
| 5 | André | FinTech SaaS Série A | 120 func | SaaS B2B | Clientes pedem voz no produto, build 6m R$500k vs Vapi $10k/m | R$500k build |
| 6 | Patrícia | CaféCerto Franquias | 200 unid | Franquia | Script não padronizado, 0800 R$80k resolve 40% | R$80k/m |
| 7 | Ricardo | ContaFácil Contábil | 35 cont. | Serviços | 500+ clientes WhatsApp, perde prazo DARF/SPED | R$12k/m estag. |
| 8 | Juliana | InglêsTotal EdTech | 150 prof | Educação | Churn falta contato, call center R$25k reativa 8% | R$25k/m |
| 9 | Marcos | FreteRápido Logística | 60 mot. | Logística | Motorista liga, dispatcher 1:15, erro rota R$2k | R$15k/m |
| 10 | Fernanda | LexSmart Jurídico | 20 adv | Legal | Adv 40% tempo triagem BANT jurídico | R$160k/m hora téc. |
| 11 | Sérgio | SuperBom Varejo | 90 func | Supermercado | Dono sem BI, `vendas por SKU/região` demora 3 dias planilha | R$0 (tempo dono) |
| 12 | Ana | HealthData Clínicas | 40 func | Saúde+Dados | Diretora precisa `prever no-show` e `lifetime` sem cientista | R$0 (sem time dados) |

---

## Roteiro 90min

### Abertura (5min)

**PM:** “Sem demo. Quero ouvir dor real e se o que construímos resolve. Se não, prefiro saber agora. 2min cada: maior dor voz/dados/atendimento hoje?”

### Round 1 — Dores (20min)

**Roberto (Clínica):** “Secretária 8-18h. Depois lead cai no Zap Business e ninguém responde. Perco 30% agendamentos. Chatbot R$200 trava em `qual convênio?`. Plantonista R$3,5k não fecha.”

**Mariana (Imóveis):** “2 SDRs R$9k cada, 40 ligações/dia. Um agenda 3 visitas, outro 1. Turnover 40%. Follow-up 14 dias esquecem. Lead frio perde.”

**Felipe (E-commerce):** “Suporte 3 turnos R$48k. NPS 6,2. FAQ bot resolve, mas troca/estorno/rastreio trava. Reclame Aqui explode.”

**Carla (Agência):** “5 clientes `IA no WhatsApp` no trimestre. Voiceflow/Vapi R$15k setup + R$3k/m. Cliente quer R$2k/m. Sem time técnico, sem white-label.”

**André (SaaS):** “ERP varejo. Cliente final quer voz no Zap. Build 6m 3 eng R$500k. Buy Vapi $0,05/min escala $10k/m. Preciso LGPD, self-hosted, API embed, multi-tenant real.”

**Patrícia (Franquia):** “200 unidades, cada franqueado atende diferente. Script 12 etapas ninguém segue. 0800 R$80k resolve 40%. Preciso mesmo script, auditoria 100%, custo por unidade, onboarding lote 200.”

**Ricardo (Contábil):** “500 clientes no Zap. Sócio responde entre declaração. Perde prazo. Estagiário R$12k não entende `DARF SPED Simples`. Bot genérico não entende jargão.”

**Juliana (EdTech):** “Aluno cancela sem contato. Reativação manual 8%. Call center R$25k script robótico. Preciso voz PT-BR natural que conhece `nível, professora, última aula` e agenda aula experimental.”

**Marcos (Logística):** “Motorista prefere ligar: `carga, nota, endereço`. Dispatcher 1:15 sobrecarregado. Erro rota R$2k. App não usa.”

**Fernanda (Jurídico):** “Adv 2h/dia triagem `área, valor causa, urgência, docs`. 20 adv = R$160k/m hora técnica perdida. Lead preenche site errado.”

**Sérgio (Varejo):** “Sou dono, não tenho analista. `Qual SKU vendeu mais em SP mês passado?` Leva 3 dias planilha. Quero perguntar em PT-BR e receber gráfico.”

**Ana (HealthData):** “Quero prever `no-show` e `LTV` mas sem time dados. Contratar cientista R$18k/m. Preciso AutoML que explique trade-off e risco.”

### Round 2 — Apresentação (5min)

**PM:** “AIOS — dois pilares, um agente multi-canal:

**Voz:** `SDR (BANT+GPCT+agenda+follow-up 14d)`, `Closer (SPIN+MEDDIC+calculator)`, `Suporte (RAG+escala humano)`. TTS `Kokoro 82M $0/min` 72 vozes `pm_alex/pf_dora` PT-BR nativo, STT `Whisper self-hosted`. LLM à escolha `OpenAI/Anthropic/Google/DeepSeek/Muse PT/Ollama`, troca `.env` sem rebuild.

**Dados:** `Analyst (gpt-4o)` — `sql_query` + `python_sandbox` + `http_request`, `LIMIT 100`, pandas/matplotlib, salva via `storage_save`, explica PT-BR. `Scientist (o3-mini)` — AutoML sklearn, GridSearch, intervalo confiança, trade-off. Pergunta: `Qual SKU vendeu mais?` → SQL → gráfico. `Preveja churn` → modelo → risco.

**Multi-canal nativo:** Mesmo agente, mesma memória, **WhatsApp hero** via `Evolution API v2.3.7 Cloud API oficial Meta` (QR 30s, template, mídia, botões, grupos, webhook). Voice+Texto no mesmo número. `E-mail, Slack, Telegram, Discord, Web` inclusos. **Evolution instances por plano:** Free 0, Starter 1 nº, Pro 3 nºs, Enterprise 10+.

**Plataforma:** Multi-tenant org isolation, governança, event-driven + DLQ, OTEL+Grafana, Stripe fixo+metered `voice_minutes/llm_tokens` + webhook usage, white-label total Enterprise `voz.seudominio.com`.

**Preço:** Starter R$89/m (10 agentes, 10k min voz), Pro R$249/m (50 agentes, 50k min, 10 orgs), Enterprise volume 500+ agentes, ilimitado, SSO/BAA, bulk CSV, white-label.”

### Round 3 — Validação (40min)

**Roberto — COMPRA Starter R$89**
> ✅ “Agenda 24/7 + RAG convênio + $0/min + pm_alex resolve.”
> ❓ “WhatsApp oficial Meta?” PM: “Evolution Cloud API oficial, documentado, QR ou API oficial, 1 instance Starter cobre 1 número.” Roberto: “Onboarding 1h? Fecho hoje. ROI 39x.” **Compromisso:** piloto 30d, meta 20 agendamentos fora horário.

**Mariana — COMPRA Pro R$249**
> ✅ “SDR 24/7 + follow-up 14d + 5 agentes (luxo/padrão/aluguel/comercial) + multi-canal (Zap+Web).”
> ❓ “Pipedrive?” PM: “http_request 30min.” “Closer negocia?” PM: “MEDDIC descobre budget, humano fecha R$450k.” Mariana: “ROI 72x, fecho anual com trial 30d.”

**Felipe — COMPRA Enterprise**
> ✅ “RAG trocas/estornos + escala humano + multi-canal.”
> ❌ “Auditoria 100% LGPD?” PM: “Postgres+S3+Whisper, Conversas com replay+CSV, SIEM webhook Enterprise.” “Zendesk?” PM: “http_request 15min.” Felipe: “ROI 6x, preciso SLA 99,9% BAA.” **POC 60d 10k min.**

**Carla — COMPRA Enterprise White-label**
> ✅ “White-label domínio próprio, org isolada, custo marginal zero.”
> 💡 “R$1,5k setup + R$800/m/cliente, margem 80%, 5 clientes = R$4k/m.” PM: “Pro rodapé discreto, Enterprise sem branding.” Carla: “Fixo, não revenue share. Preço WL?” **Contrato revenda semana.**

**André — COMPRA Enterprise Embedded**
> ✅ “Self-hosted VPC, LGPD, white-label total, org_id por cliente varejista.”
> ❌ “Billing metered?” PM: “voice_minutes_used + llm_tokens webhook 6h, JWT 24h.” André: “Build 6m → 2 semanas. Volume 10k min base + overage.” **POC 3 clientes beta.**

**Patrícia — COMPRA Enterprise Multi**
> ✅ “1 agente padrão 200 unid, script único, Grafana por unidade.”
> 💡 “Bulk CSV lote?” PM: “POST /dashboard/voice/bulk-onboard, 1 dia 200 unid.” Patrícia: “ROI 16x, piloto 10 unid mês1, contrato 12m cláusula NPS<8 saída.”

**Ricardo — COMPRA Pro R$249**
> ✅ “RAG jargão DARF/SPED + Domínio via http_request + cron prazos. Teams por contador.”
> ❓ “Treinamento?” PM: “2h Pro, Discord 4h.” Ricardo: “ROI 48x, piloto 5 contadores.”

**Juliana — COMPRA Pro R$249**
> ✅ “pm_alex natural + RAG histórico aluno + agenda experimental. A/B voz vs texto mesmo agente.”
> 💡 “Onboarding boas-vindas também.” Juliana: “ROI 100x, meta reativação 8%→25%, piloto 500 leads.”

**Marcos — COMPRA Enterprise**
> ✅ “Voz 24/7 entende carga/nota/endereço + http_request TMS SOAP. Latência <1,5s (Kokoro 300ms+LLM 800ms).”
> ❌ “TMS legado SOAP?” PM: “http_request faz SOAP 2h.” Marcos: “Demo latência ao vivo, se <1,5s fecho piloto 3m.” **ROI 10x (5 rotas R$10k/m).**

**Fernanda — COMPRA Pro→Enterprise**
> ✅ “BANT jurídico + agenda advogado certo + ficha Astrea/ProJuris.”
> 💡 “20 adv 2h/dia = R$160k/m hora, agente libera 80% = R$1,6M liberado.” Fernanda: “ROI 400x, piloto 5 adv, meta <30min triagem/dia, escala Enterprise.”

**Sérgio — COMPRA Starter R$89 (Data)**
> ✅ “Pergunto `Qual SKU mais vendeu em SP mês passado?` — Analyst faz sql_query LIMIT 100 + python_sandbox gráfico, explica PT-BR. Não preciso analista 3 dias.”
> ❓ “Conecta meu Postgres?” PM: “sql_query vault, credencial segura, só SELECT com limit.” Sérgio: “ROI imediato, piloto 2 perguntas/semana, se gráfico ok fecho Starter.”

**Ana — COMPRA Pro R$249 (Data)**
> ✅ “Scientist AutoML `prever no-show` — define métrica+baseline, GridSearch, intervalo confiança, explica risco. Sem cientista R$18k.”
> ❓ “Preciso subir CSV?” PM: “read_file + sql_query, ou http_request DW.” Ana: “Piloto no-show 1k consultas, se AUC>0,75 fecho Pro.”

### Round 4 — Objeções (15min)

| Objeção | Quem | Resposta | OK? |
|---|---|---|---|
| Evolution Cloud API oficial? | Roberto, André | Sim, v2.3.7, QR + Cloud API, docs + 1 instance Starter | ✅ |
| Whisper custo? | Felipe | Self-hosted large-v3 $0/min (GPU) / small $0 (CPU) | ✅ |
| Latência voz-a-voz? | Marcos | Kokoro 300-500ms + LLM streaming <1,5s, demo ao vivo | ✅ |
| LLM alucina preço? | Mariana | calculator valida, RAG só KB, temp 0,4 Suporte | ✅ |
| Lock-in? | André | Open core MIT, export JSON, seus dados | ✅ |
| Escala Zap 1k msg/s? | Patrícia | Evolution cluster + Redis queue 5k msg/s | ✅ |
| LGPD/BAA? | Felipe | Enterprise MSA/BAA/DPA | ✅ |
| Bulk 200 unid? | Patrícia | CSV bulk-onboard 1 dia | ✅ |
| SQL seguro? | Sérgio | vault, LIMIT 100, sem SELECT * | ✅ |
| AutoML confiável? | Ana | intervalo confiança + suposições declaradas | ✅ |

### Round 5 — Fechamento (5min)

| ICP | Plano | Valor Ano | ROI | Próximo passo |
|---|---|---|---|---|
| Roberto | Starter | R$1.068 | 39x | Onboarding 1h |
| Mariana | Pro | R$2.988 | 72x | Trial 30d |
| Felipe | Ent | R$60k+ | 6x | POC 60d |
| Carla | Ent WL | R$50k+ | novo rev | Contrato revenda |
| André | Ent Emb | R$100k+ | time-market | Integra 2 sem |
| Patrícia | Ent Multi | R$60k+ | 16x | Piloto 10 unid |
| Ricardo | Pro | R$2.988 | 48x | Piloto 5 cont |
| Juliana | Pro | R$2.988 | 100x | Piloto 500 leads |
| Marcos | Ent | R$40k+ | 10x | Demo latência |
| Fernanda | Pro→Ent | R$2.9k→120k | 400x | Piloto 5 adv |
| Sérgio | Starter | R$1.068 | tempo | Piloto 2 perguntas |
| Ana | Pro | R$2.988 | 18k econ. | Piloto no-show 1k |

**Pipeline 12 ICPs: ~R$327k ARR** (sem contar expansão Sérgio/Ana dados).

---

## Síntese — Vale lançar?

**✅ 12/12 comprariam** (3 Starter, 5 Pro, 4 Enterprise)
**✅ Dor real + orçamento existente (10-100x)**
**✅ Diferencial defensável:** $0/min TTS vs $0,05-0,10 gringo, PT-BR nativo, multi-tenant nativo (3 canais: direto, agência revenda, SaaS embed, franquia), open core, 1-click Coolify, **agora + Dados** (ninguém entrega Voz+Dados multi-canal no mesmo agente)
**✅ Novo: Dados amplia ICP** (Sérgio/Ana) sem canibalizar Voz — mesmo dashboard, mesmo billing

**Gaps P0 fechados:** Evolution Cloud API docs, Whisper profile voice-stt, metered webhook, bulk CSV, white-label toggle, **novo:** Data Analyst/Scientist templates, multi-canal WhatsApp hero na home

**Posicionamento final:**
> “A única plataforma Voz & Dados self-hosted com TTS $0/min, PT-BR nativo, multi-canal real (WhatsApp hero via Evolution Cloud API) e SQL+Python sandbox. Um agente atende WhatsApp, Web, E-mail, Slack sem perder contexto. Deploy 5min Coolify.”

**Go-to-market:**
- M1: Beta público Voz+Dados + 3 Enterprise design partners (Felipe, André, Patrícia)
- M2: Partner agências (Carla+10) + case Sérgio (BI 3 dias → 3min)
- M3: SaaS embed + franquia + case Ana (no-show AUC)

**Métricas 90d:** 50+ orgs (10 Ent), R$150k+ ARR, NPS>50, churn<5% Ent, 3 cases (Voz, Dados, Multi-canal)

**Veredito: SIM, lançar.** 12/12 validado, pipeline R$327k, gaps fechados, home 178.105.181.38:8777 já exibe Voz+Dados+Multi-canal WhatsApp.

