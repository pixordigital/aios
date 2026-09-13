# Simulação de Descoberta de Produto — AIOS Voice Agents

**Contexto:** Produto = AIOS (AI Operating System) — plataforma self-hosted para criar agentes de voz (SDR/Closer/Suporte) com TTS Kokoro ($0/min), orquestração multi-agente, integração WhatsApp/Evolution, CRM nativo. Preços: Free / Starter R$89/mês / Pro R$249/mês / Enterprise custom.

---

## Participantes

| Perfil | Empresa | Porte | Dor Principal |
|--------|---------|-------|---------------|
| **PM Lead** | AIOS (produto) | — | Facilitador |
| **Roberto** | Clínica OdontoPrime | 12 func. | Perde leads fora do horário; secretária sobrecarregada |
| **Mariana** | Imobiliária VivaReal | 45 corretores | SDR humano caro (R$4k/mês); follow-up inconsistente |
| **Felipe** | E-commerce ModaFit | 80 func. | Suporte 24/7 custa R$15k/mês; NPS caiu pra 6.2 |
| **Carla** | Agência GrowthLab | 8 func. | Clientes pedem "IA no WhatsApp"; não tem como entregar |
| **André** | SaaS FinTech (Série A) | 120 func. | Precisa voice agent no produto; build vs buy dilemma |
| **Patrícia** | Rede Franquias CaféCerto | 200 unidades | Padronizar atendimento; franqueados não seguem script |

---

## Roteiro da Conversa (90 min)

### 1. Abertura (5 min)

**PM Lead:** "Obrigado pelo tempo. Não vou fazer demo — quero ouvir suas dores reais e se o que estamos construindo resolve. Se não resolve, prefiro saber agora. Vamos direto: qual a maior dor de voz/atendimento hoje?"

---

### 2. Round 1: Dores Atuais (20 min)

**Roberto (Clínica 12p):**
> "Minha secretária atende 8h. Depois das 18h e fim de semana, lead cai no WhatsApp Business e ninguém responde. Perco ~30% dos agendamentos. Tentei chatbot barato (R$200/mês) — cliente odeia, trava no 'qual convênio?', desiste. Contratar plantonista custa R$3.5k/mês + encargos. Não fecha conta."

**Mariana (Imobiliária 45 corretores):**
> "Tenho 2 SDRs humanos. Custo R$9k/mês cada (salário + comissão + benefícios). Um faz 40 ligações/dia, qualifica 15, agenda 3 visitas. O outro faz metade. Turnover 40% ao ano — treino 3 meses pra perder. Follow-up no WhatsApp? Esquecem. Perco lead frio que viraria quente em 14 dias."

**Felipe (E-commerce 80p):**
> "Suporte 24/7 = 3 turnos x 4 agentes = R$48k/mês só folha. Mais ferramentas, treinamento, gestão. NPS 6.2. Reclamação #1: 'demora pra responder'. #2: 'não resolveu, transferiu 3x'. Tentei Intercom + bot — resolve FAQ, mas pedido complexo (troca, estorno, rastreio) trava. Cliente xinga no Reclame Aqui."

**Carla (Agência 8p):**
> "5 clientes pediram 'IA no WhatsApp' esse trimestre. Orcei R$15k/setup + R$3k/mês pra cada usando ferramentas gringas (Voiceflow, Vapi, Retell). Margem fina. Cliente quer 'paga R$2k/mês e resolve'. Não tenho time técnico pra manter. Preciso white-label que eu gerencio."

**André (SaaS Série A 120p):**
> "Nosso produto é ERP pro varejo. Clientes pedem 'voz no WhatsApp pro meu cliente final'. Build: 6 meses, 3 engenheiros, R$500k. Buy: Vapi/Retell custa $0.05/min + LLM — escala pra $10k/mês rápido. Preciso controle de dados (LGPD), self-hosted, white-label no meu domínio. Não achei ainda."

**Patrícia (Franquia 200 unidades):**
> "Cada franqueado atende do jeito dele. Script oficial = 12 etapas. Ninguém segue. Reclamação do cliente final: 'liguei na unidade X, disseram uma coisa; liguei na Y, outra'. Central 0800 custa R$80k/mês e resolve 40%. Preciso: agente único, mesmo script, mesmo tom, auditoria 100%, custo previsível por unidade."

---

### 3. Round 2: Apresentação Conceitual (10 min)

**PM Lead:** "Resumo do que estamos construindo:
- **Agentes de voz prontos:** SDR (qualifica BANT+GPCT, agenda), Closer (SPIN+Challenger+MEDDIC), Suporte (RAG + escala humano)
- **TTS self-hosted Kokoro:** 72 vozes, $0/min, roda em 1 CPU / 1.5GB RAM — seu servidor, seus dados
- **LLM à escolha:** OpenAI, Anthropic, Google, DeepSeek, Muse (PT nativo), Ollama local — troca no .env, sem rebuild
- **Orquestração:** Time hierárquico (Orquestrador → Manager → Voz) com memória compartilhada
- **Integrações nativas:** Evolution API (WhatsApp), CRM (deal create/update), calendário, webhooks
- **Dashboard:** Cria agente em 4 passos, preview de voz ao vivo, versionamento, auditoria
- **Preço:** Starter R$89/mês (1 agente, 10k min), Pro R$249/mês (5 agentes, 50k min), Enterprise volume"

---

### 4. Round 3: Reações & Validação (35 min)

#### Roberto (Clínica) — **COMPRARIA Starter R$89**

> **✅ Resolve:** "Agenda fora do horário? Resolve. $0/min TTS? Resolve. PT-BR nativo (pm_alex)? Resolve."
>
> **❌ Bloqueio:** "Como conecto no meu WhatsApp Business oficial? Tenho API oficial Meta, não Evolution."
>
> **PM:** "Evolution API conecta na API oficial Meta (Cloud API ou on-prem). A gente documenta. Quer ajuda no setup?"
>
> **Roberto:** "Se vcs fazem o onboarding (1h call), fecho hoje. R$89/mês vs R$3.5k plantonista = no-brainer."
>
> **💰 Valor percebido:** R$3.500/mês economizado → **ROI 39x**

#### Mariana (Imobiliária) — **COMPRARIA Pro R$249**

> **✅ Resolve:** "SDR 24/7 consistente, follow-up automático 14 dias, custo fixo previsível. 5 agentes = 1 SDR master + 4 nichos (luxo, padrão, aluguel, comercial)."
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

#### Felipe (E-commerce) — **COMPRARIA Enterprise**

> **✅ Resolve:** "Suporte 24/7 por fração do custo. RAG carrega base de conhecimento (trocas, estornos, rastreio). Escala humano pro complexo."
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

#### Carla (Agência) — **COMPRARIA Pro + Revenda**

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
> **PM:** "Modelo: vc paga Enterprise fixo + revende livre. Ou revenue share 20% se preferir. Qual prefere?"
>
> **Carla:** "Fixo previsível. Me dá preço Enterprise white-label?"

#### André (SaaS Série A) — **COMPRARIA Enterprise Embedded**

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

#### Patrícia (Franquia) — **COMPRARIA Enterprise Multi-Unidade**

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

### 5. Round 4: Objeções & Dealbreakers (15 min)

| Objeção | Quem | Resposta PM | Resolvido? |
|---------|------|-------------|------------|
| "Whisper transcrição custo extra?" | Felipe | "Opcional. Self-hosted Whisper large-v3 = $0/min (1 GPU). Cloud $0.006/min." | ✅ |
| "Latência voz-a-voz?" | Todos | "Kokoro local: 300-500ms TTS. LLM streaming: 200-800ms. Total <1.5s. Demo ao vivo?" | ✅ |
| "E se LLM alucina preço/promoção?" | Mariana | "Governance: `calculator` tool valida math. RAG só responde com base no KB. Temperature 0.4 suporte." | ✅ |
| "Migração de chatbot atual?" | Roberto | "Import FAQ → RAG. Prompt template migra lógica. 2h assistido." | ✅ |
| "Suporte técnico em PT-BR?" | Carla | "Slack connect + email SLA 4h (Pro) / 1h (Enterprise). Docs PT-BR completas." | ✅ |
| "Lock-in?" | André | "Open core (MIT). Self-hosted = vc owns data, models, infra. Export agents/teams JSON anytime." | ✅ |
| "Escala WhatsApp (1k msg/s)?" | Patrícia | "Evolution API cluster + Redis queue. Load test 5k msg/s ok. Docs de scaling." | ✅ |

---

### 6. Fechamento & Compromissos (5 min)

| Participante | Decisão | Próximo Passo | Valor Anual Estimado |
|--------------|---------|---------------|---------------------|
| Roberto (Clínica) | **Sim — Starter** | Onboarding 1h essa semana | R$1.068 |
| Mariana (Imobiliária) | **Sim — Pro** | Trial 30 dias + migração assistida | R$2.988 |
| Felipe (E-commerce) | **Sim — Enterprise** | POC 60 dias (10k min) → contrato | R$60k+ |
| Carla (Agência) | **Sim — Enterprise White-label** | Definir preço revenda + contract | R$50k+ |
| André (SaaS) | **Sim — Enterprise Embedded** | Integração API 2 semanas | R$100k+ |
| Patrícia (Franquia) | **Sim — Enterprise Multi** | Piloto 10 unidades mês 1 | R$60k+ |

**Pipeline gerado: ~R$274k ARR em 6 conversas.**

---

## Lições do Produto

### ✅ Validado — Fortes Sinais de Compra
1. **Self-hosted TTS ($0/min) = killer feature** — todos citaram custo variável como dor #1
2. **PT-BR nativo (pm_alex/Muse) = diferencial** — gringos falham em PT
3. **Dashboard 4-passos = "non-technical ready"** — agências e PMEs compram sem dev
4. **Multi-tenant nativo = abre canal agência + SaaS embed** — 2 canais de distribuição
5. **Preço fixo previsível vs variável (Vapi/Retell) = argumento de venda #1**

### ⚠️ Gaps Críticos (Resolver Antes do Launch)
1. **Evolution API Cloud API (Meta oficial)** — documentar + testar; hoje só on-prem Evolution
2. **Whisper self-hosted one-click** — add no docker-compose.coolify.yml
3. **Billing metered webhook** — implementar `voice_minutes_used` event + docs
4. **Bulk onboarding API** — CSV → agents/teams/channels para franquias
5. **SLA/Contrato Enterprise** — jurídico preparar MSA, BAA, SLA templates
6. **White-label branding removal** — toggle no config (Enterprise only)

### 🎯 Posicionamento Refinado
> **"O único voice agent platform self-hosted com TTS $0/min, PT-BR nativo, multi-tenant nativo, e preço fixo previsível. Deploy em 1h no Coolify. White-label para agências e SaaS."**

---

## Próximos Passos (Product Team)

| Ação | Owner | Prazo |
|------|-------|-------|
| Evolution Cloud API docs + test | Backend | 1 semana |
| Whisper one-click deploy | DevOps | 3 dias |
| Metered billing webhook | Backend | 1 semana |
| Bulk onboarding API | Backend | 2 semanas |
| Enterprise MSA/BAA/SLA templates | Legal + PM | 2 semanas |
| White-label branding toggle | Frontend | 1 semana |
| Case study Roberto (clínica) — gravar call | PM + Marketing | 2 semanas |
| Pricing page update (Enterprise "fale conosco") | PM | 3 dias |
| Demo video 5 min (SDR + Closer + Support) | PM + Eng | 1 semana |
| Outbound para 50 ICPs (lista acima) | Sales + PM | Contínuo |

---

## Conclusão

**Vale a pena lançar? SIM.**

- **6/6 ICPs comprariam** (1 Starter, 1 Pro, 4 Enterprise)
- **Pipeline qualificado: R$274k ARR** em conversas únicas
- **Dor real, urgente, orçamento existente** (todos já gastam 10-100x mais)
- **Diferenciais defensáveis:** self-hosted $0/min, PT-BR, multi-tenant, open core
- **Canais de distribuição claros:** direto PME, agências (revenda), SaaS (embed), franquias (multi-unidade)

**Risco principal:** execução Enterprise (SLA, suporte, jurídico, onboarding scale). Resolver gaps acima antes de aceitar contratos Enterprise grandes.

**Recomendação:** Launch **Beta Público em 4 semanas** (resolver gaps 1-3), **Enterprise Private Beta com 3 design partners** (Felipe, André, Patrícia) em paralelo. Go-to-market agressivo agências + SaaS embed mês 2.