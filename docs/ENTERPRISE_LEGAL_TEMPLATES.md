# Enterprise Legal Templates — AIOS

> Modelos prontos para Enterprise: MSA + BAA/DPA (LGPD) + SLA 99,9%. Ajuste com jurídico antes de assinar.

---

## 1. MSA — Master Service Agreement (resumo)

**Partes:** Contratante (Cliente) e Pixor AIOS (Fornecedor). **Objeto:** licença de uso da plataforma AIOS self-hosted (Voz & Dados, multi-canal, Evolution API).

- **Licença:** não exclusiva, intransferível, por `org_id` + `LICENSE_KEY`. Uso conforme plano (Free/Starter/Pro/Enterprise).
- **Hospedagem:** Cliente hospeda no VPS dele (Coolify/compose). Fornecedor mantém Control Plane (`control.aios.dev`) para `billing/licença/heartbeat`.
- **Pagamento:** Stripe, mensal, fatura dia 1. Inadimplência: `past_due` (banner 3 dias) → `suspended` (7 dias, só `/billing` libera) → `canceled` (14 dias, dump 30 dias).
- **Tamper:** Alterar `plan` via DB/patch sem autorização = `tamper_score` + `auto-suspend` + `blacklist` (5 anos, base LGPD legítimo interesse fraude).
- **Propriedade:** Dados do Cliente são dele. Código AIOS é nosso (MIT open core + enterprise add-ons fechados).
- **Rescisão:** 30 dias aviso. Export JSON de `agents/teams/conversations` em 30 dias.
- **Foro:** São Paulo/SP.

---

## 2. BAA / DPA — LGPD (Encarregado + Medidas)

**Controlador:** Cliente. **Operador:** Pixor AIOS (quando processa dados no Control Plane: `heartbeat` com `org_id`, `usage`, `email`).

**Medidas:**
- Criptografia TLS 1.3 `control.aios.dev` + `Evolution API` via TLS.
- Postgres central com `encrypt_secret` para `webhook_url` e `api_key`.
- `auditoria 100%` opcional: áudio `S3/MinIO` + transcrição `Whisper` com retenção configurável (30/90 dias).
- `RLS` por `org_id` em todas as tabelas (`Organization`, `User`, `Agent`, `Conversation`).
- `heartbeat` coleta só `image_digest`, `public_key_fp`, `plan_claim`, `usage` — **não** coleta conteúdo de conversa por padrão (opt-in `log_content=true`).
- **Suboperadores:** Stripe (pagamento), Hetzner/Coolify (infra Control Plane), S3 (se habilitado).
- **Encarregado (DPO):** `dpo@aios.dev`.

**Direitos do titular:** Cliente responde. AIOS apoia em 5 dias úteis.

---

## 3. SLA 99,9% — Enterprise

| Métrica | Alvo | Medição | Crédito |
|---|---|---|---|
| Disponibilidade `control.aios.dev` (verify/heartbeat) | 99,9% mensal | `uptime` Grafana + `blackbox` | 10% se <99,9%, 25% se <99% |
| Latência voz-a-voz `Kokoro local + LLM` | p95 <1,5s | `voice_tts_duration` OTEL | tuning sem crédito |
| Suporte | P1 (suspensão) 1h, P2 4h, P3 1 dia útil | `help@aios.dev` + Slack Connect Enterprise | — |
| RTO/RPO Control Plane | RTO 4h, RPO 1h | Backup diário Postgres Central | — |

**Exclusões:** `VPS do Cliente` fora do SLA (ele gerencia), `Evolution API` dele, `LLM` externo (OpenAI/Anthropic), `internet` do Cliente.

**Manutenção:** janela dom 02:00-04:00 BRT com aviso 48h.

---

## 4. Checklist de Assinatura

- [ ] `AIOS_LICENSE_KEY` gerado (hmac `org_id`)
- [ ] `AIOS_IMAGE_DIGEST` + `CONTROL_PUBLIC_KEY` na imagem
- [ ] `Stripe price` mapeado (`starter/pro/enterprise`)
- [ ] `BAA` assinado + `DPO` notificado
- [ ] `Slack Connect` criado (Enterprise)

**Contato:** `sales@aios.dev` / `support@aios.dev`
