# Simulação Final — AIOS Voz & Dados Multi-canal 1-Click BYOK

**Produto hoje:** `Voz (SDR/Closer/Suporte WhatsApp-first)` + `Dados (Analyst gpt-4o + Scientist o3-mini)` • `Multi-canal` `WhatsApp hero Evolution API Cloud API` • `CRM 100% IA` `kanban + HITL` • `TTS Kokoro $0/min` + `Whisper $0` • `1 comando curl BYOK` `VPS dele + key dele` • `Multi-tenant white-label` • `Deploy Coolify ou VPS puro`

**Mesa:** PM Lead + 11 ICPs + Sales + Eng

---

## ICPs (11)

| # | Nome | Empresa | Porte | Foco | Dor | O que precisa da ferramenta |
|---|------|---------|-------|------|-----------------------------------------------|
| 1 | Roberto | OdontoPrime | MEI 12 func | Clínica | Lead 18h-8h perdido, plantonista R$3,5k | `WhatsApp 24/7 que agenda`, `1-click sem TI`, `pagar só R$89 + tokens dele` |
| 2 | Mariana | VivaReal | 45 corretores | Imobiliária | 2 SDRs R$18k, turnover 40%, follow-up 14d falha | `SDR Zap que não esquece follow-up`, `Pipedrive 1-click`, `5 agentes por nicho` |
| 3 | Felipe | ModaFit | 80 func | E-commerce | Suporte 24/7 R$48k, NPS 6,2, troca/estorno trava | `RAG trocas + escala humano com contexto`, `Zendesk 1-click`, `auditoria 100% LGPD` |
| 4 | Carla | GrowthLab | 8 func | Agência | 5 clientes `IA no Zap`, gringo R$15k setup | `White-label voz.seudominio.com`, `org isolada por cliente`, `revenda R$800/m` |
| 5 | André | FinTech SaaS | 120 func | SaaS | Build voz 6m R$500k vs Vapi $10k/m | `Self-hosted VPC, BYOK, multi-tenant org_id por cliente, billing metered webhook` |
| 6 | Patrícia | CaféCerto | 200 unid | Franquia | Script 12 etapas não seguido, 0800 R$80k 40% | `1 agente padrão 200 unid, bulk CSV 1 dia, Grafana por unidade, 10+ instances Zap` |
| 7 | Ricardo | ContaFácil | 35 cont | Contábil | 500 clientes Zap, perde DARF/SPED | `Entende jargão contábil via RAG, integra Domínio, cron prazos, team por contador` |
| 8 | Juliana | InglêsTotal | 150 prof | EdTech | Churn falta contato, reativa 8% com call center R$25k | `Voz pm_alex natural + RAG histórico aluno, agenda aula experimental, A/B voz vs texto` |
| 9 | Marcos | FreteRápido | 60 mot. | Logística | Dispatcher 1:15, erro rota R$2k, motorista só liga | `Voz entende carga/nota/endereço + TMS SOAP tempo real, latência <1,5s` |
| 10 | Sérgio | SuperBom | 90 func | Varejo | Dono sem BI, `SKU por região` 3 dias planilha | `Pergunta PT-BR → SQL LIMIT 100 → gráfico, sem analista, BYOK barato DeepSeek` |
| 11 | Ana | HealthData | 40 func | Saúde Dados | Prever no-show sem cientista R$18k | `AutoML no-show, intervalo confiança, explica risco, sobe CSV` |

---

## Round 1 — Dores + O que precisam (2min cada)

**Roberto:** “Preciso que o Zap responda 24/7, entenda `convênio`, agende na agenda real, sem contratar plantonista. Preciso instalar sozinho, sem Dev, em 5min, e pagar só plataforma + meus tokens. Não quero pagar token pra vocês.”

**Mariana:** “Preciso SDR que faça follow-up 14 dias sozinho no Zap, sem esquecer, e que crie deal no Pipedrive 1-click, não webhook genérico que eu mapeio 30min. E 1 número Zap por nicho (luxo/padrão/aluguel).”

**Felipe:** “Preciso RAG que resolve troca/estorno/rastreio e escala humano com todo contexto, e que gere ticket Zendesk 1-click. E auditoria 100% áudio+transcrição pra LGPD, e SLA 99,9% com BAA assinado.”

**Carla:** “Preciso revender: `voz.minhamarca.com`, sem `Powered by AIOS`, cada cliente vê só dele, eu sou super-admin, e custo marginal zero (BYOK dele). E 1 comando pra subir VPS do cliente.”

**André:** “Preciso embedar no meu ERP: `org_id` por varejista, `VPS dele` mas `licença nossa` com `heartbeat 6h` e `suspend` se não pagar, e `webhook usage` pra eu cobrar meu cliente por minuto.”

**Patrícia:** “Preciso 1 agente padrão pra 200 franquias, bulk CSV que cria `agent+team+channel+Evolution instance` em 1 dia, e painel franqueador com `conversão/NPS por unidade`.”

**Ricardo:** “Preciso que entenda `DARF, SPED, Simples`, integre `Domínio`, lembre prazos via `cron`, e que cada contador veja só seus clientes.”

**Juliana:** “Preciso voz `pf_dora` que conhece `nível, professora, última aula` e agenda, e que eu possa A/B testar `voz vs texto` no mesmo agente, mesmo número.”

**Marcos:** “Preciso atender ligação, entender `carga`, consultar `TMS SOAP` legado em tempo real, e responder em <1,5s, senão motorista desliga.”

**Sérgio:** “Preciso perguntar `Qual SKU vendeu mais em SP mês passado?` e receber tabela+gráfico em 10s, sem escrever SQL, com `LIMIT 100` seguro, usando minha key DeepSeek barata.”

**Ana:** “Preciso `prever no-show` com `o3-mini` AutoML, que me diga `AUC, intervalo confiança, trade-off` e que eu suba `CSV` sem código.”

---

## Round 2 — PM apresenta solução atual (com o que eles pediram)

**PM:** “Tudo que vocês pediram já está na home `178.105.181.38:8777` e no `install.sh`:

- **Voz WhatsApp-first:** `SDR BANT+GPCT`, `Closer SPIN+MEDDIC+calculator`, `Suporte RAG` — cada um `WhatsApp+Web+E-mail` multi-canal, mesmo `Evolution instance` atende texto e voz `Kokoro $0/min`. `instances por plano` na home: Free 0, Starter 1 nº, Pro 3, Enterprise 10+.

- **Dados:** `Analyst gpt-4o` `sql_query LIMIT 100 + python_sandbox` e `Scientist o3-mini` AutoML — pergunta PT-BR, devolve gráfico. Sérgio/Ana: BYOK `deepseek-v4-flash $0,15/1M` ou `Muse PT`.

- **CRM 100% IA:** `crm_create_deal` cria no kanban + `Pipedrive/Zendesk/Astrea 1-click` via `PIPEDRIVE_API_KEY` etc (fechamos gap), `crm_update_deal` move `prospection→closed_won`, `HITL` se desconto >15% ou `closed_won >R$5k`.

- **1 comando BYOK:** `curl -fsSL https://raw.githubusercontent.com/pixordigital/aios/main/install.sh | bash` — instala `Docker` → `clone /opt/aios` → gera `.env` (`POSTGRES/REDIS/JWT`) → `docker compose --profile voice up -d` → `health/live` → cria `admin`. Você cola **sua** `OpenRouter key`, tokens vão na **sua** fatura, nós só medimos pra limite do plano. `VPS puro` ou `--with-coolify`.

- **Multi-tenant + white-label + bulk:** `POST /dashboard/voice/bulk-onboard` CSV 200 unid, `white_label` toggle remove branding, `voz.seudominio.com`, `heartbeat 6h JWT 24h` com `auto-suspend` se inadimplente + `blacklist`.

- **Legal Enterprise:** `docs/ENTERPRISE_LEGAL_TEMPLATES.md` com `MSA + BAA/DPA LGPD + SLA 99,9%` pronto pra jurídico.”

---

## Round 3 — Validação: resolve? compram? o que falta?

**Roberto — Starter R$89 + tokens dele → COMPRA**
> “BYOK perfeito, 1 comando sem TI resolve. WhatsApp 24/7 + convênio via RAG + agenda. **Preciso:** `1 instance Starter` já cobre meu 1 número, e `QR 30s` sem Meta burocrático. Fecho se onboarding 1h. **ROI 39x**.”

**Mariana — Pro R$249 → COMPRA**
> “Pipedrive 1-click que vocês fecharam era o gap. `5 agentes por nicho` + `follow-up 14d` + `multi-canal` (Zap+Web) resolve turnover. **Preciso:** `3 instances Pro` pra luxo/padrão/aluguel. Fecho anual trial 30d. **ROI 72x**.”

**Felipe — Enterprise → COMPRA**
> “Zendesk 1-click + RAG + auditoria 100% + BAA que vocês entregaram desbloqueia. **Preciso:** `SLA 99,9%` assinado + `Whisper self-hosted` pra LGPD (não mandar áudio pra OpenAI). Fecho POC 60d 10k min. **ROI 6x**.”

**Carla — Enterprise WL → COMPRA**
> “White-label total + `1 comando por cliente VPS` + `BYOK dele` (eu não pago token dele) fecha revenda. **Preciso:** `margem 80%` mantida, sem revenue share. Fecho 5 clientes piloto. **Novo rev R$50k**.”

**André — Enterprise Embedded → COMPRA**
> “Self-hosted VPC + `heartbeat` + `webhook usage` pra eu cobrar meu varejista é exatamente o `build vs buy` resolvido. **Preciso:** `org_id por cliente` isolado + `JWT 24h` pra offline 24h. Fecho POC 3 clientes beta. **R$100k**.”

**Patrícia — Enterprise Multi → COMPRA**
> “Bulk CSV 1 dia + `10+ instances` + Grafana por unidade resolve 200 franquias. **Preciso:** `script único` travado (franqueado não edita) + `cláusula NPS<8 saída`. Piloto 10 unid. **ROI 16x**.”

**Ricardo — Pro → COMPRA**
> “Jargão contábil RAG + `Domínio` via `http_request` + `cron prazos` + team por contador. **Preciso:** `treinamento 2h não-tech` (vocês já tem playbook). Piloto 5 contadores. **ROI 48x**.”

**Juliana — Pro → COMPRA**
> “`pf_dora` + RAG histórico + `A/B voz vs texto` mesmo agente/número é diferencial. **Preciso:** `agenda experimental` no calendário real. Piloto 500 leads reativação 8%→25%. **ROI 100x**.”

**Marcos — Enterprise → COMPRA (condicional)**
> “TMS SOAP + voz <1,5s é o teste. **Preciso:** `demo latência ao vivo` hoje. Se <1,5s, fecho piloto 3m. **ROI 10x**.”

**Sérgio — Starter R$89 → COMPRA**
> “Analyst `LIMIT 100` + gráfico 10s sem SQL + `DeepSeek BYOK $0,15/1M` resolve `3 dias → 3min`. **Preciso:** `vault Postgres` seguro (não expor senha no prompt). Fecho piloto 2 perguntas/semana.”

**Ana — Pro R$249 → COMPRA**
> “Scientist `no-show` com `AUC+intervalo+risco` sem cientista R$18k. **Preciso:** `subir CSV` via `read_file` sem código (já tem). Piloto 1k consultas, meta AUC>0,75.”

---

## Objeções finais + o que ainda precisam

| Precisa | Quem | Já entregue? | Falta |
|---|---|---|---|
| `1-click sem TI` | Roberto, Carla | ✅ `curl install.sh` | Só documentar vídeo 2min |
| `BYOK tokens na fatura dele` | Todos | ✅ `AIOS_OPENROUTER_API_KEY` dele, medimos só limite | Explicar na home/pricing que `BYOK` |
| `Pipedrive/Zendesk/Astrea 1-click` | Mariana, Felipe, Fernanda | ✅ `aios/tools/crm.py` presets | Testar com conta real deles (30min) |
| `3 instances Pro` pra nicho | Mariana | ✅ home pricing `Pro 3` | — |
| `Whisper self-hosted LGPD` | Felipe | ✅ `profile voice-stt` | Docs `STT $0` |
| `White-label total` | Carla | ✅ `white_label` toggle | — |
| `Bulk 200 unid` | Patrícia | ✅ `POST /bulk-onboard` | — |
| `Treinamento 2h` | Ricardo | Playbook pronto, falta vídeo | 1 sem |
| `A/B voz vs texto` | Juliana | ✅ mesmo agente, 2 canais, métrica por canal já existe | Só filtro no dashboard |
| `TMS SOAP` exemplo | Marcos | `http_request` faz SOAP, falta snippet | 1 dia |
| `Vault Postgres` | Sérgio | `sql_query` via vault, já `LIMIT 100` | — |
| `CSV sem código` | Ana | `read_file` já | — |

---

## Fechamento

| ICP | Plano | Ano | ROI | O que precisa pra assinar (pedidos apontados) |
|---|---|---|---|---|
| Roberto | Starter | R$1.068 | 39x | `WhatsApp 24/7` + `RAG convênio` + `agenda real` + `1 instance Starter` + `QR 30s` + `1-click install.sh sem TI` + `BYOK tokens dele` + onboarding 1h |
| Mariana | Pro | R$2.988 | 72x | `SDR follow-up 14d automático Zap` + `Pipedrive 1-click PIPEDRIVE_API_KEY` + `3 instances Pro (luxo/padrão/aluguel)` + `5 agentes por nicho` + teste com conta real |
| Felipe | Ent | R$60k | 6x | `RAG trocas/estornos` + `Zendesk 1-click` + `auditoria 100% áudio+transcrição S3` + `Whisper self-hosted LGPD` + `BAA/DPA + SLA 99,9% assinado` + POC 60d 10k min |
| Carla | Ent WL | R$50k | novo | `White-label voz.seudominio.com sem branding` + `org isolada por cliente (super-admin)` + `1 comando VPS por cliente` + `BYOK dele (custo marginal zero)` + contrato revenda margem 80% |
| André | Ent | R$100k | time | Integra 2 sem |
| Patrícia | Ent | R$60k | 16x | `Bulk CSV 200 unid (agent+team+Evolution instance em 1 dia)` + `10+ instances Enterprise` + `script único travado (franqueado não edita)` + `Grafana por unidade` + `cláusula NPS<8 saída` + piloto 10 |
| Ricardo | Pro | R$2.988 | 48x | `RAG jargão DARF/SPED/Simples` + `integra Domínio via http_request` + `cron lembrete prazos` + `team por contador (isolado)` + `treinamento 2h não-tech` + piloto 5 |
| Juliana | Pro | R$2.988 | 100x | `Voz pf_dora PT-BR natural` + `RAG histórico aluno (nível/professora/última aula)` + `agenda aula experimental calendário real` + `A/B voz vs texto mesmo agente/número` + piloto 500 reativação 8%→25% |
| Marcos | Ent | R$40k | 10x | `Voz entende carga/nota/endereço` + `consulta TMS SOAP legado tempo real` + `latência p95 <1,5s (Kokoro 300ms)` + `demo ao vivo hoje` + piloto 3m |
| Sérgio | Starter | R$1.068 | tempo | `Analyst gpt-4o pergunta PT-BR → sql_query LIMIT 100 + python_sandbox gráfico 10s` + `vault Postgres seguro` + `BYOK DeepSeek $0,15/1M` + piloto 2 perguntas/semana |
| Ana | Pro | R$2.988 | R$18k | `Scientist o3-mini AutoML no-show` + `AUC + intervalo confiança + trade-off` + `subir CSV via read_file sem código` + piloto 1k consultas AUC>0,75 |

**Pipeline 11 ICPs: ~R$325k ARR**

---

## Vale lançar?

**SIM — 11/11 compram.** Dor real + orçamento 10-100x + `1-click BYOK` remove barreira `TI` + `WhatsApp hero` + `CRM 100% IA` + `Voz+Dados` cobre 2 orçamentos (atendimento + BI) no mesmo `R$89`.

**O que precisam mais (lista curta pra lançar):**
1. Vídeo 2min `install.sh` + `QR Evolution` (Roberto/Carla)
2. Teste `Pipedrive/Zendesk` com conta real (Mariana/Felipe) — já 1-click, só validar
3. `BAA` assinado (Felipe) — template já em `docs/ENTERPRISE_LEGAL_TEMPLATES.md`
4. Vídeo treinamento 2h contábil + snippet `TMS SOAP` (Ricardo/Marcos) — 1 dia

**Gaps críticos zero bloqueante.** Lançar `beta público` agora + `Enterprise private beta` com `Felipe/André/Patrícia`.

