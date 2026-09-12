# Reunião Marketing + Copy — Home 178.105.181.38:8777

**Data:** 2026-09-13 14:00 — 15:00 (60min)  
**Participantes:**

| Papel | Quem | Foco |
|-------|------|------|
| **Marketing Lead** | PMM | Posicionamento, ICP, concorrência |
| **Copywriter** | Senior, 8 anos B2B SaaS | Voz, clareza, conversão |
| **Designer** | UI | Hierarquia, escaneabilidade |
| **PMM** | — | Pricing, prova social |

**Input:** Home atual `website/index.html` (hero `v0.2.0 — 100% Autônomo • 24/7...`, status bar 4 itens, seções Voice/Data/Features/Channels/Pricing)

**Objetivo:** Deixar textos **mais profissionais** e **dizerem o necessário** — sem jargão, sem repetição, sem prometer demais. Cada seção deve responder 1 pergunta do ICP em 5s.

---

## 1. Diagnóstico — O que está pouco profissional hoje (Copywriter)

**Copywriter projetou a home atual na tela e marcou:**

| Local | Problema | Exemplo |
|-------|----------|---------|
| **Hero badge** | `v0.2.0 — 100% Autônomo • 24/7 • HITL • Voice Agents GA` → lista técnica, não benefício | ICP Roberto não sabe o que é `HITL` |
| **Hero título** | `Agentes 100% Autônomos 24/7 que você controla` → redundante (`100%` + `24/7` + `você controla` = 3 ideias) | Falta 1 promessa clara |
| **Hero desc** | `Autônomos: ReAct 3 trials + Reflexion + HITL (>R$5k, ≥10% desconto, delete) — contornam "tá caro" sozinhos.` → jargão de engenharia no hero | PME não entende ReAct/Reflexion |
| **Status bar** | 4 itens (`Autônomo 100% + HITL`, `24/7 sem bloqueio`, `TTS $0/min`, `PT-BR`) → 4 é muito, 2 é ideal | `24/7 sem bloqueio` é confuso (bloqueio de quê?) |
| **Voice section** | `SDR 10-seções prompt template` → detalhe interno, não valor | Cliente quer `agenda reunião`, não `10-seções` |
| **Data section** | `Senior SQL vault + python_sandbox + viz` → técnico | Dono quer `pergunte em português, receba gráfico` |
| **Features** | 6 cards com `👥 Multi-Tenant Real` etc → ok, mas `Governança Enterprise` com `allow/deny tools, orçamentos` → jargão | Simplificar para `Controle total` |
| **Pricing** | `R$89` vs `Vapi $500+` → comparação boa, mas `Starter 10k min voz/mês` → cliente não sabe quantos minutos usa | Traduzir para `~500 conversas/mês` |
| **Geral** | Repetição `100% autônomo` 5x na página → perde força | Dizer 1x forte no hero, depois provar com `como` |

**Marketing Lead:** "Home atual fala como engenheiro para engenheiro. Nosso ICP é **dono de clínica, gestor de franquia, dona de agência** — precisa falar como **dono de negócio para dono de negócio**."

**Designer:** "E hierarquia: hero com 4 linhas de texto + 4 status + 2 botões = muito. Precisa **1 título + 1 subtítulo de 1 linha + 1 prova + 1 CTA**."

---

## 2. Princípios de Copy Aprovados (todos)

1. **1 ideia por seção** — hero responde `O que é?` em 5s, não lista tudo
2. **Benefício > Feature** — `24/7` → `Nunca perde lead fora do horário` (dor de Roberto)
3. **Número concreto > jargão** — `R$249` → `Economize R$8k/mês vs SDR`
4. **Prova > promessa** — `100% autônomo` → mostrar `Timeline Trials/Reflexões` (print)
5. **PT-BR simples** — sem `ReAct`, `Reflexion`, `HITL` no hero (deixa para docs)

---

## 3. Antes → Depois (decisão)

### Hero

**Antes:**
> `v0.2.0 — 100% Autônomo • 24/7 • HITL • Voice Agents GA`
> `Agentes 100% Autônomos 24/7 que você controla`
> `Autônomos: ReAct 3 trials + Reflexion + HITL (>R$5k, ≥10% desconto, delete) — contornam "tá caro" sozinhos. Voz 24/7: SDR/Closer/Suporte — TTS Kokoro $0/min PT-BR (pm_alex), Evolution WhatsApp. Dados: Analyst/Scientist — SQL + Python, 100% autônomo com lineage. 1-click Coolify.`

**Depois (aprovado):**
> `✓ Novo — Atende 24/7 e aprende sozinho`
> `WhatsApp que vende e agenda sozinho — dia e noite`
> `Substitui SDR por R$249/mês. Se disser "tá caro", ele calcula seu ROI e contorna sozinho. Se for desconto >10% ou valor >R$5k, pede sua aprovação. Voz PT-BR real, sem pagar por minuto.`

**Por quê:** 1 promessa (vende e agenda sozinho) + 1 prova (contorna "tá caro") + 1 segurança (pede aprovação) + 1 diferencial (voz PT-BR sem por minuto). Sem jargão.

### Status Bar (4 → 3)

**Antes:** `Autônomo 100% + HITL | 24/7 sem bloqueio | TTS $0/min | PT-BR nativo`
**Depois:** `24/7 — Nunca perde lead | Autônomo com aprovação humana | $0/min — Sem surpresa`

**Por quê:** `24/7` vira benefício (nunca perde lead), `HITL` vira `com aprovação humana` (segurança), `$0/min` mantém (prova).

### Voice Section

**Antes:** `SDR 10-seções prompt template` + `lead_score + calculator`
**Depois:** `SDR agenda reunião sozinho. Se falar "tá caro", mostra economia de 97% e agenda.`

**Por quê:** Dono não quer saber de `10-seções`, quer `agenda`.

### Data Section

**Antes:** `Senior SQL vault + python_sandbox + viz`
**Depois:** `Pergunte "vendas ontem?" em português — receba tabela + gráfico + o que fazer.`

### Features

**Antes:** `Governança Enterprise — Níveis de autonomia, allow/deny tools, orçamentos`
**Depois:** `Controle total — Você define quando ele pede sua aprovação (valor, desconto) e vê tudo que fez.`

### Pricing

**Antes:** `10k min voz/mês`
**Depois:** `~500 conversas/mês` + `Economize R$8k/mês vs SDR` (ROI calculator já tem)

---

## 4. Textos Finais Aprovados (para dev implementar)

**Hero badge:** `✓ Novo — Atende 24/7 e aprende sozinho`

**Hero título:** `WhatsApp que vende e agenda sozinho — dia e noite`

**Hero subtítulo:** `Substitui SDR por R$249/mês. Se disser "tá caro", ele calcula seu ROI e contorna sozinho. Se for desconto >10% ou valor >R$5k, pede sua aprovação. Voz PT-BR real, sem pagar por minuto.`

**Hero CTA:** `Testar 14 dias grátis →` (primário) + `Ver WhatsApp →` (secundário, âncora `#channels`)

**Status bar:**
- `24/7 — Nunca perde lead`
- `Autônomo com aprovação humana`
- `$0/min — Sem surpresa`

**Voice section título:** `Voz e WhatsApp que atendem como seu melhor SDR`
**Voice desc:** `Mesmo agente atende texto e voz no mesmo número. Fora do horário, agenda para amanhã 9h. Dentro do horário, qualifica e agenda. Tudo com voz PT-BR real.`

**Data section título:** `Pergunte aos seus dados em português`
**Data desc:** `Conecte seu Postgres. Pergunte "vendas ontem vs média?" e receba tabela, gráfico e o que fazer — sem escrever SQL.`

**Features título:** `Controle total, sem sustos`
**Features desc:** `Você vê tudo que ele fez (trials, reflexões, skills) e define quando ele pede sua aprovação.`

---

## 5. Checklist Pós-Implementação

- [ ] Hero 1 título + 1 subtítulo de 2 linhas + 1 CTA (não 4)
- [ ] Status bar 3 itens (não 4)
- [ ] Voice/Data sem jargão ReAct/Reflexion (mover para docs)
- [ ] Pricing com `~500 conversas` + `Economize R$8k`
- [ ] Teste 5s: mostrar para Roberto (clínica) e perguntar "o que faz?" — deve responder "WhatsApp que vende sozinho"

**Próximo:** Dev implementa `website/index.html` com textos acima + commit `feat: home copy profissional`.

**Assinaturas:**

Marketing Lead: _________________  Copywriter: _________________  Designer: _________________  Data: 2026-09-13
