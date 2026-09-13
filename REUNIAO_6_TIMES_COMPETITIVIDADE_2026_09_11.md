# Reunião 6 Times — O que passou despercebido e deixaria a ferramenta mais completa e competitiva

**Data:** 2026-09-11 15:30
**Times:** SWE, Produto, Comercial, Cyberseg, Dados, WhatsApp/Voz
**Facilitador:** PM Lead
**Objetivo:** Listar funcionalidades não consideradas que aumentariam `competitividade` + `helpfulness` (sem virar `portal` genérico)

---

## 1. SWE — “O que dói na operação e ninguém pediu”

| # | Funcionalidade | Por que passou despercebida | Impacto | Esforço |
|---|---|---|---|---|
| S1 | **Flow Builder visual `Zap+Voz+Dado`** `drag-and-drop` que gera `workflow` `http_request` + `crm_*` + `rag_search` sem `code` | Focamos `CLI` + `dashboard` `4 passos`, mas `agência` `Carla` quer `sem código` | `10x` `agência` `sem dev` | `2 sem` (reusa `flow_editor.html` + `Workflow` model) |
| S2 | **Versionamento + `rollback` 1-click `prompt`/`voz`** | Temos `AgentVersion` mas sem `diff` UI | `Segurança` `Sérgio` `testa prompt` sem medo | `3 dias` |
| S3 | ** `playground` `A/B` `voz vs texto` mesmo `agent` ** | `Juliana` pediu `A/B` e fizemos só `canal` separado, não `split` 50/50 | `EdTech` prova `voz 25%` vs `texto 8%` | `1 sem` |
| S4 | ** `bulk edit` `speed/voz` p/ 200 franquias ** | `Patrícia` bulk `create` ok, mas `update` `speed` de `200` ainda é 1 a 1 | `Franquia` escala | `2 dias` |

## 2. Produto — “O que ICP pediu sem falar”

| # | Funcionalidade | ICP que sofreria quieto | Impacto |
|---|---|---|---|
| P1 | ** `inbox` unificado `multi-canal` com `atribuição humana`** `WhatsApp+Voz+E-mail` na mesma `conversa` com `quem responde` | `Felipe` `NPS 6,2` `transferiu 3x` | `Helpfulness` `★` |
| P2 | ** `template builder` `Meta` aprovado** `fora da janela 24h` | `Patrícia` `franquia` dispara `promoção` | `Compliance` `evita 131047` |
| P3 | ** `agendamento real` `Google Calendar/Calendly`** não só `calculator` | `Roberto` `agenda consulta` `Mariana` `visita` | `Fecha loop` |
| P4 | ** `pagamento` `Pix/Stripe` no `Zap`** `cobrar no chat` | `SuperBom` `varejo` + `CaféCerto` | `Monetiza` `+R$` |

## 3. Comercial — “O que faz fechar ou perder pra `Tallk/WhatsGW`”

| # | Funcionalidade | vs Concorrente | Impacto |
|---|---|---|---|
| C1 | **`tabela comparativa` + `ROI calculator` na `home`** `R$18k SDR vs R$249` `72x` | `Tallk` não mostra `ROI` | `Conversão` `+20%` |
| C2 | **`case` em vídeo `30s` por `ICP`** `Roberto 20 agendamentos` | `WhatsGW` só `docs` | `Prova` |
| C3 | **`free trial` `14d` sem `cartão` com `1 instance Zap` real (não `mock`)** | `Meta Business Agent` `grátis` | `Ativação` |
| C4 | **`parceiro` `white-label` `revenue share` automático** `Stripe Connect` | `Agência` `Carla` quer `margem 80%` | `Canal` `10 agências` |

## 4. Cyberseg — “O que falta pra `BAA` não ser `checklist`”

| # | Funcionalidade | Risco hoje | Fix |
|---|---|---|---|
| Y1 | **`redação` `PII` `auto` no `log`/`transcrição`** `CPF, cartão` `***` | `LGPD` `vaza log` | `regex` `CPF/RG` no `tracing.py` + `whisper` |
| Y2 | **`consent` `opt-in` `Zap` com `template` `opt-out` `STOP`** | `Meta` `bloqueia número` | `flow` `STOP → pause bot 24h` |
| Y3 | **`2FA` `opcional` mas `admin` sem `2FA` pode `delete org`** | `takeover` | `forçar 2FA` pra `superadmin` + `delete` com `OTP` |
| Y4 | **`backup` `S3` `versioning` + `restore` 1-click `dashboard`** | `Ransomware` `deleta S3` | `deploy/backup.sh` já existe, só `cron` + `botão` |

## 5. Dados — “O que `Analyst/Scientist` não faz e `dono` precisa”

| # | Funcionalidade | Dor `Sérgio/Ana` | Impacto |
|---|---|---|---|
| D1 | **`alerta` `proativo` `Analyst`** `vendas caiu 12% ontem vs média 7d` `push Zap` | `Dono` só pergunta, não é avisado | `Proatividade` |
| D2 | **`dashboard` `BI` `embed` `metabase/superset` no `/dashboard/analytics`** | `Sérgio` quer `BI` sem sair `AIOS` | `Retenção` |
| D3 | **`linhagem` `SQL` `explica de onde veio o número`** `tabela.coluna → cálculo` | `Ana` `AUC 0,75` mas `de onde veio dado?` | `Confiança` |
| D4 | **`feature store` `no-show` com `refresh` `diário` `cron`** | `Ana` `treina hoje, dado muda amanhã` | `Precisão` |

## 6. WhatsApp/Voz — “O que `Kokoro` + `Evolution` não entrega e `cliente` sente”

| # | Funcionalidade | Dor | Fix |
|---|---|---|---|
| W1 | **`barge-in` `interromper` `voz` + `silence detection` `800ms`** | `Marcos` `motorista` fala em cima, `SDR` não interrompe | `voice-stream` `VAD` + `LiveKit` `turn detection` |
| W2 | **`SSML` `pausa` `ênfase` `número por extenso` `R$ 1.500 → mil e quinhentos reais`** | `Ricardo` `DARF R$ 1.500` soa `um ponto cinco` | `Kokoro` `text_processor` `pt-br` `number→words` |
| W3 | **`gravação + transcrição` `call` `100%` com `busca` `“onde falou preço?”`** | `Felipe` `auditoria` `LGPD` | `Whisper` `large-v3` já `S3`, só `UI` `play + search transcript` |
| W4 | **`fila humana` `round-robin` `load balancer` `Zap+Voz`** `H2H` | `Felipe` `3 turnos` `48k` `transferiu 3x` | `Team` `routing_strategy` `round_robin` já existe, só `UI` `fila` |

---

## Priorização — RICE + `competitividade`

| Rank | Func | RICE | Time | Esforço | Entrega | Por que agora |
|---|---|---|---|---|---|---|
| **1** | **W3 gravação+busca** | 9 | Voz | 1 sem | já `Whisper S3`, só `UI` | `Felipe` `auditoria` `Enterprise` fecha `R$60k` |
| **2** | **P1 inbox unificado** | 8 | Produto | 2 sem | `Conversa` já `multi-canal` | `NPS` `6,2→8` `helpfulness` máximo |
| **3** | **S1 flow builder** | 8 | SWE | 2 sem | `agência` sem `dev` | `Carla` `10 agências` canal |
| **4** | **C1 ROI calculator home** | 7 | Comercial | 3 dias | `72x` na `home` | `conversão` |
| **5** | **D1 alerta proativo** | 7 | Dados | 1 sem | `Analyst` `push` `vendas caiu` | `dono` `proatividade`  vazia |
| **6** | **Y1 redação PII** | 7 | Cyberseg | 3 dias | `CPF ***` `LGPD` | `BAA` sem `checklist` |
| **7** | **P3 agendamento real** | 6 | Produto | 1 sem | `Google Calendar` `OAuth` | `fecha loop` `Roberto/Mariana` |
| **8** | **W1 barge-in** | 6 | Voz | 2 sem | `VAD` `LiveKit` | `motorista` `Marcos` |
| **9** | **S2 versionamento rollback** | 6 | SWE | 3 dias | `diff` `prompt` | `segurança` |
| **10** | **Y4 backup restore 1-click** | 5 | Cyberseg | 2 dias | `cron` `S3` `botão` | `Enterprise` `RTO` |

**Não fazer agora (pós-PMF):** `W2 SSML` `número por extenso` (já `pt-br` numbers ok), `D2 BI embed` (usa `Grafana` já), `C2 vídeo case` (depois `3 cases`).

---

## Decisão

**Lançar `beta` com `Top 3` (`W3+P1+S1`) em `sprint 2 semanas` + `hardening` `C5/C8/C10` já `done`.** `Top 3` deixam a ferramenta **completa** ( `voz` gravável + `inbox` humano + `sem código`) e **competitiva** vs `Tallk/WhatsGW` (eles não têm `gravação+busca` + `inbox` + `flow` num só).

**Dono:** `SWE` `W3`, `Produto` `P1`, `SWE` `S1`. `Review` em `2026-09-25`.

