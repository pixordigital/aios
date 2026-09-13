# Simulação de Validação de Produto — AIOS Voice Agents

**Produto:** AIOS — Plataforma self-hosted de agentes de voz (SDR/Closer/Suporte) com TTS Kokoro $0/min, PT-BR nativo, multi-tenant, white-label. Deploy 1-click Coolify.

**Formato:** Mesa redonda virtual (90 min) — 10 ICPs + PM Lead + 2 observadores (Sales/Eng)

---

## Participantes (10 ICPs Reais)

| # | Nome | Empresa | Porte | Segmento | Dor Principal | Orçamento Atual |
|---|------|---------|-------|----------|---------------|-----------------|
| 1 | **Roberto** | Clínica OdontoPrime | 12 func | Saúde | Leads perdidos fora horário; plantonista R$3.5k/mês | R$3.5k/mês |
| 2 | **Mariana** | Imobiliária VivaReal | 45 corretores | Imobiliário | SDR humano caro (R$9k/cada); turnover 40%; follow-up falha | R$18k/mês |
| 3 | **Felipe** | E-commerce ModaFit | 80 func | Varejo | Suporte 24/7 = R$48k/mês; NPS 6.2; bot trava em caso complexo | R$48k/mês |
| 4 | **Carla** | Agência GrowthLab | 8 func | Marketing | 5 clientes pedem "IA no WhatsApp"; ferramentas gringas R$15k setup + R$3k/mês | R$0 (novo rev) |
| 5 | **André** | SaaS FinTech (Série A) | 120 func | SaaS B2B | Clientes pedem voice no produto; build 6m vs buy $10k/mês Vapi | R$500k (build) |
| 6 | **Patrícia** | Franquias CaféCerto | 200 unidades | Franquia | Padronizar atendimento; central 0800 R$80k/mês resolve 40% | R$80k/mês |
| 7 | **Ricardo** | Contabilidade ContaFácil | 35 contadores | Serviços | 500+ clientes WhatsApp; responde manual; perde prazos | R$12k/mês (estag) |
| 8 | **Juliana** | Educação InglêsTotal | 150 professores | EdTech | Aluno cancela por falta contato; reativação manual não escala | R$25k/mês (call center) |
| 9 | **Marcos** | Logística FreteRápido | 60 motoristas | Logística | Motorista liga pra central; dispatcher sobrecarregado; erros de rota | R$15k/mês |
| 10 | **Fernanda** | Jurídico LexSmart | 20 advogados | LegalTech | Lead qualifica sozinho? Não. Advogado gasta 40% tempo triagem | R$0 (tempo adv) |

---

## Roteiro da Conversa

---

### ABERTURA (5 min)

**PM Lead:** "Obrigado a todos. Não vou fazer demo — quero ouvir suas dores reais e se o que construímos resolve. Se não resolve, prefiro saber agora. Cada um: 2 min — qual sua maior dor de voz/atendimento hoje?"

---

### ROUND 1: DORES ATUAIS (20 min)

#### 1. Roberto — Clínica OdontoPrime (12 func)
> "Minha secretária atende 8h–18h. Depois das 18h e fim de semana, lead cai no WhatsApp Business e ninguém responde. Perco ~30% dos agendamentos. Tentei chatbot barato (R$200/mês) — cliente odeia, trava no 'qual convênio?', desiste. Contratar plantonista custa R$3.5k/mês + encargos. Não fecha conta. **Preciso: atende 24/7, entende convênio, agenda na agenda real, custo fixo baixo.**"

#### 2. Mariana — Imobiliária VivaReal (45 corretores)
> "Tenho 2 SDRs humanos. Custo R$9k/mês cada (salário + comissão + benefícios). Um faz 40 ligações/dia, qualifica 15, agenda 3 visitas. O outro faz metade. Turnover 40% ao ano — treino 3 meses pra perder. Follow-up no WhatsApp? Esquecem. Perco lead frio que viraria quente em 14 dias. **Preciso: SDR 24/7 consistente, follow-up automático 14 dias, custo previsível, zero turnover.**"

#### 3. Felipe — E-commerce ModaFit (80 func)
> "Suporte 24/7 = 3 turnos x 4 agentes = R$48k/mês só folha. Mais ferramentas, treinamento, gestão. NPS 6.2. Reclamação #1: 'demora pra responder'. #2: 'não resolveu, transferiu 3x'. Tentei Intercom + bot — resolve FAQ, mas pedido complexo (troca, estorno, rastreio) trava. Cliente xinga no Reclame Aqui. **Preciso: resolve trocas/estornos/rastreio via RAG, escala humano com contexto, 24/7, custo 1/10.**"

#### 4. Carla — Agência GrowthLab (8 func)
> "5 clientes pediram 'IA no WhatsApp' esse trimestre. Orcei R$15k/setup + R$3k/mês pra cada usando ferramentas gringas (Voiceflow, Vapi, Retell). Margem fina. Cliente quer 'paga R$2k/mês e resolve'. Não tenho time técnico pra manter. **Preciso: white-label no meu domínio, gerencio clientes no dashboard, custo marginal ~zero, deploy simples.**"

#### 5. André — SaaS FinTech Série A (120 func)
> "Nosso produto é ERP pro varejo. Clientes pedem 'voz no WhatsApp pro meu cliente final'. Build: 6 meses, 3 engenheiros, R$500k. Buy: Vapi/Retell custa $0.05/min + LLM — escala pra $10k/mês rápido. Preciso controle de dados (LGPD), self-hosted, white-label no meu domínio, API-first pra embed no meu produto. **Não achei ainda.**"

#### 6. Patrícia — Franquias CaféCerto (200 unidades)
> "Cada franqueado atende do jeito dele. Script oficial = 12 etapas. Ninguém segue. Reclamação do cliente final: 'liguei na unidade X, disseram uma coisa; liguei na Y, outra'. Central 0800 custa R$80k/mês e resolve 40%. **Preciso: agente único, mesmo script, mesmo tom, auditoria 100%, custo previsível por unidade, onboarding em lote 200 unidades.**"

#### 7. Ricardo — Contabilidade ContaFácil (35 contadores)
> "500+ clientes no WhatsApp. Sócio responde manual entre declarações. Perde prazos, cliente reclama no CRC. Contratar estagiário R$1.5k cada x 8 = R$12k/mês + treinamento contábil. Bot genérico não entende 'DARF', 'SPED', 'simples nacional'. **Preciso: entende jargão contábil, integra com Domínio/Contmatic, lembra prazos, escala só o complexo.**"

#### 8. Juliana — Educação InglêsTotal (150 professores)
> "Aluno cancela por falta de contato. Tentamos reativação manual — liga, não atende, WhatsApp, não responde. Call center terceirizado R$25k/mês, script genérico, aluno sente que é robô. Taxa reativação 8%. **Preciso: voz natural PT-BR, conhece histórico do aluno (nível, professora, última aula), agenda aula experimental, custo por reativação < R$5.**"

#### 9. Marcos — Logística FreteRápido (60 motoristas)
> "Motorista liga pra central: 'carga não chegou', 'endereço errado', 'preciso nota fiscal'. Dispatcher sobrecarregado — 1 atende 15 motoristas. Erro de rota = R$2k prejuízo. Tentei app — motorista não usa, prefere ligar. **Preciso: atende ligação, entende 'carga', 'nota', 'endereço', consulta TMS em tempo real, devolve resposta na hora, 24/7.**"

#### 10. Fernanda — Jurídico LexSmart (20 advogados)
> "Advogado gasta 40% do tempo triando lead: 'é trabalhista?', 'valor da causa?', 'prazo?'. Lead qualifica sozinho no site? Não — preenche errado. Perde-se 2h/dia por advogado = R$160k/mês em hora técnica. **Preciso: qualifica BANT+GPCT jurídico (área, valor, urgência, docs), agenda consulta com advogado certo, preenche ficha automática.**"

---

### ROUND 2: APRESENTAÇÃO CONCEITUAL (5 min)

**PM Lead:** "Resumo do AIOS Voice Agents:
- **3 templates prontos:** SDR (BANT+GPCT+agenda), Closer (SPIN+MEDDIC+calculator), Suporte (RAG+escala humano)
- **TTS self-hosted Kokoro:** 72 vozes, **$0/min**, roda em 1 CPU / 1.5GB RAM — seu servidor, seus dados
- **LLM à escolha:** OpenAI, Anthropic, Google, DeepSeek, Muse (PT nativo), Ollama local — troca no .env
- **Orquestração:** Time hierárquico (Orquestrador → Manager → Voz) com memória compartilhada
- **Integrações nativas:** Evolution API (WhatsApp oficial), CRM, calendário, webhooks, HTTP tools
- **Dashboard:** Cria agente em 4 passos, preview voz ao vivo, versionamento, auditoria 100%
- **Multi-tenant nativo:** Agências revendem, SaaS embed, franquias gerenciam 200+ unidades
- **Preço:** Starter R$89/mês (1 agente, 10k min), Pro R$249/mês (5 agentes, 50k min), Enterprise volume + white-label"

---

### ROUND 3: REAÇÕES & VALIDAÇÃO (40 min)

#### Roberto (Clínica) — **COMPRA Starter R$89/mês**
> **✅ Resolve:** "Agenda fora horário? Resolve. $0/min TTS? Resolve. PT-BR nativo (pm_alex)? Resolve. Entende convênio? RAG carrega tabela de convênios."
>
> **❓ Bloqueio:** "Como conecto no meu WhatsApp Business **oficial**? Tenho API oficial Meta, não Evolution."
>
> **PM:** "Evolution API conecta na API oficial Meta (Cloud API ou on-prem). A gente documenta. Quer ajuda no setup?"
>
> **Roberto:** "Se vcs fazem o onboarding (1h call), fecho hoje. R$89/mês vs R$3.5k plantonista = **no-brainer**. **ROI 39x**."
>
> **Compromisso:** Piloto 30 dias, onboarding assistido, métrica: agendamentos fora horário > 20/mês.

---

#### Mariana (Imobiliária) — **COMPRA Pro R$249/mês**
> **✅ Resolve:** "SDR 24/7 consistente, follow-up automático 14 dias, custo fixo. 5 agentes = 1 SDR master + 4 nichos (luxo, padrão, aluguel, comercial)."
>
> **⚠️ Dúvida:** "Meu CRM é Pipedrive. Integra nativo?"
>
> **PM:** "Webhook genérico + http_request tool. Mapeia campos em 30 min. Tem exemplo pronto pro Pipedrive."
>
> **Mariana:** "OK. Mas o Closer — ele negocia preço? Meu ticket médio R$450k."
>
> **PM:** "Closer usa MEDDIC + calculator tool. Não decide preço final — qualifica, descobre budget, agenda reunião com corretor sênior. O humano fecha."
>
> **Mariana:** "Perfeito. R$249 vs R$18k SDRs = **ROI 72x**. Fecho Pro anual se vcs dão 30 dias trial + migração assistida."

---

#### Felipe (E-commerce) — **COMPRA Enterprise**
> **✅ Resolve:** "Suporte 24/7 por fração do custo. RAG carrega base (trocas, estornos, rastreio). Escala humano pro complexo."
>
> **❌ Bloqueio crítico:** "Preciso **auditoria 100% das conversas** (LGPD, compliance, treinamento). Export áudio + transcrição + métricas por agente. Tem?"
>
> **PM:** "Governance_config grava tudo no Postgres. Áudio no S3/MinIO. Transcrição Whisper opcional. Dashboard tem 'Conversas' com filtro, export CSV, replay áudio. Enterprise tem SIEM webhook."
>
> **Felipe:** "Show. **Integra com meu helpdesk (Zendesk)?** Cria ticket se escala?"
>
> **PM:** "http_request tool → Zendesk API. Exemplo no template Support. 15 min pra configurar."
>
> **Felipe:** "R$15k/mês → R$2.5k (Enterprise estimado) = **ROI 6x**. Mas preciso SLA 99.9%, suporte dedicado, contrato BAA. Vocês têm?"
>
> **PM:** "Enterprise = SLA custom, CS dedicated, contrato jurídico, deploy assistido. Vamos conversar valores."
>
> **Compromisso:** POC 60 dias (10k min) → contrato Enterprise.

---

#### Carla (Agência) — **COMPRA Enterprise White-label + Revenda**
> **✅ Resolve:** "White-label no meu domínio, gerencio clientes no dashboard, custo marginal ~zero (self-hosted)."
>
> **💡 Insight:** "Posso cobrar R$1.5k/setup + R$800/mês/cliente. Margem 80%. 5 clientes = R$4k/mês recorrente pra mim."
>
> **PM:** "Multi-tenant nativo (org_id isolado). Cada cliente vê só os agentes dele. Vc é super-admin."
>
> **Carla:** "Perfeito. **Preciso branding removido** (powered by AIOS sumir) e domínio custom (voz.minhaagencia.com)."
>
> **PM:** "Enterprise white-label remove branding + custom domain. Pro tem 'powered by' discreto no rodapé."
>
> **Carla:** "Fecho Enterprise white-label pra revenda. **Revenue share?**"
>
> **PM:** "Modelo: vc paga Enterprise fixo + revende livre. Ou revenue share 20% se preferir."
>
> **Carla:** "Fixo previsível. Me dá preço Enterprise white-label?"
>
> **Compromisso:** Definir preço Enterprise WL + contrato revenda essa semana.

---

#### André (SaaS Série A) — **COMPRA Enterprise Embedded**
> **✅ Resolve:** "Self-hosted no meu VPC, LGPD compliant, white-label total, API-first pra embed no meu produto."
>
> **❌ Bloqueio:** "Preciso **multi-tenant real**: meu cliente (varejista) cria agente dele no MEU painel, usa MEU WhatsApp Business Account, MEU CRM. Isolamento total."
>
> **PM:** "Arquitetura: org_id = seu cliente. Cada org tem agents, teams, channels, keys isolados. Evolution API multi-instance (uma por org). CRM keys por org. Já funciona."
>
> **André:** "E **billing metered**? Eu cobro meu cliente por minuto/ligação. Preciso webhook de uso em tempo real."
>
> **PM:** "Tracing span emite `voice_minutes_used` + `llm_tokens` por org/conversa. Webhook configurable. Pode medir e cobrar."
>
> **André:** "**Build vs Buy resolvido.** 6 meses → 2 semanas integração. **Preço Enterprise embedded?**"
>
> **PM:** "Volume-based. 10k min/mês base + overage. Vamos alinhar no contrato."
>
> **Compromisso:** Integração API 2 semanas, POC com 3 clientes beta.

---

#### Patrícia (Franquia) — **COMPRA Enterprise Multi-Unidade**
> **✅ Resolve:** "Um agente padrão, 200 unidades, script único, auditoria centralizada, custo por unidade previsível."
>
> **💡 Feature request:** "Painel franqueador: vejo métricas por unidade (conversas, conversão, NPS, aderência ao script). Alerta se unidade X cai performance."
>
> **PM:** "Dashboard tem 'Teams' por unidade. Org pai = franqueador vê tudo. Org filho = franqueado vê só o dele. Métricas agregadas no Grafana (já incluso no deploy)."
>
> **Patrícia:** "R$80k central 0800 → R$5k (Enterprise 200 unidades) = **ROI 16x**. **Preciso onboarding em lote** (CSV 200 unidades, cria agents + teams + canais auto)."
>
> **PM:** "API bulk create + Terraform/Ansible para deploy. 1 dia pra subir todas. Incluído no Enterprise."
>
> **Patrícia:** "Assino piloto 10 unidades mês 1, escala 50/mês. **Contrato 12 meses com cláusula saída se NPS < 8.**"

---

#### Ricardo (Contabilidade) — **COMPRA Pro R$249/mês**
> **✅ Resolve:** "Entende jargão contábil via RAG (carrego legislação + FAQ). Integra Domínio via http_request. Lembra prazos via cron job + tool."
>
> **⚠️ Dúvida:** "Meus 35 contadores têm logins diferentes. Cada um vê só seus clientes?"
>
> **PM:** "Sim — teams por contador, agents no team, governance_config isola dados. Ou multi-org se quiser isolamento total."
>
> **Ricardo:** "R$249 vs R$12k estagiários = **ROI 48x**. Mas preciso **treinamento pro meu time** — eles não são tech."
>
> **PM:** "Incluso no Pro: 2h training + docs PT-BR + Discord priority. Enterprise tem CS dedicated."
>
> **Ricardo:** "Fecho Pro. Começa com 5 contadores piloto mês 1."

---

#### Juliana (EdTech) — **COMPRA Pro R$249/mês**
> **✅ Resolve:** "Voz natural PT-BR (pm_alex/pf_dora), conhece histórico via RAG (nível, professora, última aula), agenda aula experimental via calendar tool."
>
> **💡 Insight:** "Posso usar pro **onboarding** também — aluno novo recebe call de boas-vindas, agenda primeira aula, escolhe professora."
>
> **PM:** "Template SDR adapta — 'boas-vindas + agenda aula experimental'. Mesmo agente, prompt diferente."
>
> **Juliana:** "R$249 vs R$25k call center = **ROI 100x**. Taxa reativação meta: 8% → 25%. **Preciso A/B test: voz vs texto.**"
>
> **PM:** "Dashboard tem canais paralelos — mesmo agent, canal voice + whatsapp texto. Métricas separadas."
>
> **Juliana:** "Fecho Pro. Piloto reativação 500 leads mês 1."

---

#### Marcos (Logística) — **COMPRA Enterprise**
> **✅ Resolve:** "Atende ligação 24/7, entende 'carga/nota/endereço' via RAG no TMS, consulta tempo real via http_request, devolve resposta na hora."
>
> **❌ Bloqueio:** "Meu TMS é legado (SOAP XML). Tem conector?"
>
> **PM:** "http_request tool faz SOAP também. Exemplo genérico + vc mapeia. 2h dev."
>
> **Marcos:** "Erro de rota = R$2k. Se evita 5/mês = R$10k economia. **Enterprise faz sentido.** Preciso **SLA voz < 2s latência** — motorista não espera."
>
> **PM:** "Kokoro local: 300-500ms TTS. LLM streaming: 200-800ms. Total <1.5s. Demo ao vivo?"
>
> **Marcos:** "Demo agora. Se <1.5s real, fecho Enterprise piloto 3 meses."

---

#### Fernanda (LegalTech) — **COMPRA Pro → Enterprise**
> **✅ Resolve:** "Qualifica BANT+GPCT jurídico (área, valor, urgência, docs), agenda consulta com advogado certo, preenche ficha automática."
>
> **💡 Diferencial:** "Advogado cobra R$500/hora. 2h/dia triagem = R$100k/mês por advogado. 20 advogados = R$2M/mês tempo. Se agente faz 80% da triagem = **R$1.6M/mês liberado**."
>
> **PM:** "Template SDR + ferramenta `lead_score` custom (área, valor, prazo) + `http_request` pro CRM jurídico (Astrea, ProJuris)."
>
> **Fernanda:** "Começo Pro 5 advogados piloto. Se libera 1h/dia cada = **ROI 400x**. Escala Enterprise todo escritório."
>
> **Compromisso:** Piloto Pro 30 dias, métrica: tempo triagem advogado < 30 min/dia.

---

### ROUND 4: OBJEÇÕES & DEALBREAKERS (15 min)

| Objeção | Quem | Resposta PM | Resolvido? |
|---------|------|-------------|------------|
| "Evolution Cloud API (Meta oficial)?" | Roberto, André | Documentado + testado. On-prem Evolution também suportado. | ✅ |
| "Whisper transcrição custo extra?" | Felipe, Patrícia | Self-hosted Whisper large-v3 = $0/min (1 GPU). Cloud $0.006/min. | ✅ |
| "Latência voz-a-voz real?" | Todos | Kokoro local 300-500ms + LLM streaming 200-800ms = <1.5s. Demo agendada. | ✅ |
| "LLM alucina preço/promoção?" | Mariana, Felipe | Governance: `calculator` valida math. RAG só responde com base no KB. Temp 0.4 suporte. | ✅ |
| "Migração chatbot atual?" | Roberto, Juliana | Import FAQ → RAG. Prompt template migra lógica. 2h assistido. | ✅ |
| "Suporte técnico PT-BR?" | Carla, Ricardo | Slack connect + email SLA 4h (Pro) / 1h (Enterprise). Docs PT-BR completas. | ✅ |
| "Lock-in?" | André | Open core (MIT). Self-hosted = vc owns data, models, infra. Export agents/teams JSON anytime. | ✅ |
| "Escala WhatsApp (1k msg/s)?" | Patrícia | Evolution API cluster + Redis queue. Load test 5k msg/s ok. Docs de scaling. | ✅ |
| "BAA/LGPD contrato?" | Felipe, André | Enterprise tem MSA, BAA, DPA templates prontos. Jurídico revisa. | ✅ |
| "Onboarding 200 unidades?" | Patrícia | Bulk API CSV → agents/teams/channels/evolution. 1 dia. Incluído Enterprise. | ✅ |

---

### ROUND 5: FECHAMENTO & COMPROMISSOS (5 min)

| ICP | Decisão | Próximo Passo | Valor Anual Estimado | ROI Projetado |
|-----|---------|---------------|---------------------|---------------|
| 1. Roberto (Clínica) | **Sim — Starter** | Onboarding 1h essa semana | R$1.068 | 39x |
| 2. Mariana (Imobiliária) | **Sim — Pro** | Trial 30 dias + migração assistida | R$2.988 | 72x |
| 3. Felipe (E-commerce) | **Sim — Enterprise** | POC 60 dias → contrato | R$60.000+ | 6x |
| 4. Carla (Agência) | **Sim — Ent WL** | Definir preço revenda + contract | R$50.000+ | Novo rev |
| 5. André (SaaS) | **Sim — Ent Embed** | Integração API 2 semanas | R$100.000+ | Time-market |
| 6. Patrícia (Franquia) | **Sim — Ent Multi** | Piloto 10 unid mês 1 | R$60.000+ | 16x |
| 7. Ricardo (Contabilidade) | **Sim — Pro** | Piloto 5 contadores mês 1 | R$2.988 | 48x |
| 8. Juliana (EdTech) | **Sim — Pro** | Piloto reativação 500 leads | R$2.988 | 100x |
| 9. Marcos (Logística) | **Sim — Enterprise** | Demo latência → piloto 3m | R$40.000+ | 10x |
| 10. Fernanda (LegalTech) | **Sim — Pro→Ent** | Piloto 5 advogados 30 dias | R$2.988 → 120k | 400x |

**Pipeline Total Qualificado: ~R$323k ARR em 10 conversas.**

---

## SÍNTESE: VALE A PENA LANÇAR?

### ✅ SINAIS FORTES DE PRODUCT-MARKET FIT

1. **10/10 ICPs comprariam** (3 Starter, 4 Pro, 3 Enterprise)
2. **Dor real, urgente, orçamento existente** — todos já gastam 10-100x mais
3. **ROI claro e mensurável** — de 6x a 400x dependendo do caso
4. **Diferenciais defensáveis:**
   - Self-hosted TTS $0/min (vs $0.05-0.30/min concorrentes)
   - PT-BR nativo (pm_alex, pf_dora, Muse Spark) — gringos falham
   - Multi-tenant nativo abre 3 canais: direto, agências (revenda), SaaS (embed)
   - Open core (MIT) — sem lock-in, auditoria total
   - Deploy 1-click Coolify — "implanta em 5 min no meu VPS"

### ⚠️ GAPS CRÍTICOS PARA LAUNCH ENTERPRISE (Resolver nas próximas 4 semanas)

| Gap | Prioridade | Esforço | Responsável |
|-----|------------|---------|-------------|
| Evolution Cloud API (Meta oficial) docs + teste | P0 | 1 semana | Backend |
| Whisper one-click deploy (profile voice-stt) | P0 | 3 dias | DevOps |
| Metered billing webhook (voice_minutes_used, llm_tokens) | P0 | 1 semana | Backend |
| Bulk onboarding API (CSV → agents/teams/channels) | P0 | 2 semanas | Backend |
| Enterprise MSA/BAA/SLA templates jurídicos | P0 | 2 semanas | Legal + PM |
| White-label branding toggle + custom domain | P1 | 1 semana | Frontend |
| SLA/Monitoring alertas (p95 latency, error rate) | P1 | 1 semana | DevOps |
| Case study gravado (Roberto clínica) | P1 | 2 semanas | PM + Mktg |

### 🎯 POSICIONAMENTO REFINADO PÓS-VALIDAÇÃO

> **"A única plataforma de voice agents self-hosted com TTS $0/min, PT-BR nativo, multi-tenant real, e preço fixo previsível. Deploy em 5 min no Coolify. White-label para agências e SaaS embed."**

**Diferenciação vs Concorrentes:**
| Concorrente | TTS Cost | PT-BR | Multi-tenant | Self-hosted | Preço |
|-------------|----------|-------|--------------|-------------|-------|
| Vapi | $0.05/min | Fraco | Não | Não | Variável |
| Retell | $0.07/min | Fraco | Não | Não | Variável |
| Voiceflow | $0.10/min | Médio | Limitado | Não | Variável |
| **AIOS** | **$0/min** | **Nativo** | **Nativo** | **Sim** | **Fixo** |

---

## PRÓXIMOS PASSOS (Product Team)

| Ação | Owner | Prazo | Status |
|------|-------|-------|--------|
| Resolver gaps P0 (Evolution Cloud, Whisper, Billing, Bulk API) | Eng | 4 semanas | 🔄 Iniciando |
| Jurídico: MSA/BAA/SLA Enterprise templates | Legal + PM | 2 semanas | ⏳ Pendente |
| White-label toggle + custom domain UI | Frontend | 1 semana | ⏳ Pendente |
| Gravar case study Roberto (clínica) — call real | PM + Mktg | 2 semanas | ⏳ Pendente |
| Demo video 5 min (SDR + Closer + Support) | PM + Eng | 1 semana | ⏳ Pendente |
| Pricing page update (Enterprise "fale conosco") | PM | 3 dias | ⏳ Pendente |
| Outbound para 50 ICPs (lista segmentada) | Sales + PM | Contínuo | 🔄 Iniciando |
| Onboarding playbook (checklist 30 min) | CS | 1 semana | ⏳ Pendente |
| Partner program agências (Carla = design partner) | PM | 2 semanas | ⏳ Pendente |
| Enterprise private beta: Felipe, André, Patrícia | PM + Eng | Paralelo | 🔄 Planejando |

---

## CONCLUSÃO FINAL

**VALE A PENA LANÇAR? SIM, COM CONDIÇÕES.**

### Condições para Launch Público (Beta):
1. ✅ Gaps P0 resolvidos (4 semanas)
2. ✅ 3 Enterprise design partners ativos (Felipe, André, Patrícia)
3. ✅ 1 case study gravado + demo video
4. ✅ Pricing page + docs PT-BR completas

### Estratégia Go-to-Market:
- **Mês 1:** Beta público + Enterprise private beta (3 partners)
- **Mês 2:** Launch geral + partner program agências (Carla + 10 convidadas)
- **Mês 3:** SaaS embed program (André + 5 convidadas) + franquia playbook (Patrícia)

### Métricas de Sucesso 90 dias:
- 50+ orgs ativas (10 Enterprise)
- R$150k+ ARR
- NPS > 50
- Churn < 5% Enterprise
- 3+ case studies publicados

---

**Assinatura do PM Lead:** _______________ **Data:** _______________

**Próxima Revisão:** 30 dias pós-launch beta