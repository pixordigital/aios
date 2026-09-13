# Reunião SWE × Cybersegurança — AIOS Voz & Dados

**Data:** 2026-09-11 14:00
**Participantes:**
- **SWE Lead** (backend, 8 anos)
- **SWE Jr** (frontend, 2 anos)
- **Cybersec Lead** (AppSec, OSCP, 10 anos)
- **Cybersec Eng** (pentest, 5 anos)
- **Arquiteto** (observador)
- **PM** (observador)

**Objetivo:** Avaliar `code quality` + `segurança geral` da aplicação `AIOS` (Voz, Dados, Multi-canal, BYOK, 1-click, Control Plane, Blacklist) e decidir: **lançar como está ou precisa hardening?**

---

## 1. Code Quality — SWE Lead

### ✅ Bom

| Área | Estado | Nota |
|---|---|---|
| **Stack** | `FastAPI + SQLAlchemy async + Alembic + pgvector + Redis + LiteLLM` | 9/10 — moderno, async, tipado |
| **Estrutura** | `aios/{api,core,db,tools,dashboard}` separado, `TOOL_REGISTRY` allow-list | 8/10 |
| **Migrations** | `Alembic` versionado (`a1b2c3d4...` + `h4b5c6... blacklist`) | 8/10 |
| **Observabilidade** | `OTEL` + `Grafana` + `tracing.py` + `audit log` | 8/10 |
| **Testes** | `tests/test_*` existe mas cobertura ~30% | 5/10 |

### ⚠️ Dívida técnica (não bloqueia launch, mas precisa roadmap)

| Encontrado | Severidade | Onde | Fix |
|---|---|---|---|
| `UnboundLocalError: select` em `evolution_page` (analytics) — `500` hoje | **P0** | `aios/dashboard/app.py:2839` `from sqlalchemy import select` sombreado + `db` fora do `async with` | **Fix já aplicado** (revertido pra simples, mas precisa re-add com `channel_connection_id` correto + `db2` scope) |
| `any` e `broad except` em `voice.py`, `tracing.py`, `license.py` | P1 | `except Exception: pass` esconde erro | Adicionar `logger.exception` com `trace_id` |
| `TOOL_REGISTRY` sem `pydantic` validação estrita em `dynamic` tools | P1 | `aios/tools/dynamic.py` | Validar `input_schema` no `register` |
| `STORAGE_DIR` local sem `volume` compartilhado em `Coolify` → perde mídia em `restart` | P1 | `aios/core/storage.py:143` warning já existe, mas sem `S3` default | Forçar `S3` em `Enterprise` (já no `install.sh` hint) |
| `password_bcrypt_rounds=12` ok, mas `scrypt` fallback sem `pepper` | P2 | `aios/api/auth.py` | ok para MVP, mas considerar `argon2` futuro |
| `TODO`/`ponytail:` debt não mapeado | P2 | `aios/core/tracing.py:100` `ponytail: in-memory idempotency` | `ponytail-debt` ledger |

**Veredito SWE:** Código **lançável como beta** com `P0` já corrigido (`evolution 500` revertido). `P1` não bloqueia, mas deve entrar no `sprint hardening` de 2 semanas antes de `Enterprise` grande.

---

## 2. Segurança — Cybersec Lead

### Metodologia: OWASP Top 10 + SANS + manual review `main.py`, `auth.py`, `voice.py`, `storage.py`, `license.py`

### ✅ Controles já bons

| Controle | Evidência | Nota |
|---|---|---|
| **Auth** `JWT` `HS256` `60m` + `refresh 30d` + `bcrypt 12` + `rate limit 5/300s` (Redis + in-memory fallback) | `aios/api/auth.py:75,135,102` | 9/10 |
| **2FA TOTP** `pyotp` + `backup codes 8` | `aios/api/auth.py:497` | 9/10 |
| **CSRF** `dashboard_csrf` `referer` check sem `token` state | `aios/main.py:432` | 8/10 |
| **CSP** `default-src 'self'` + `media-src blob:` fix hoje (`voice` `0:00` era CSP bloqueando `blob:`) | `aios/main.py:331` | 8/10 (após fix) |
| **Rate limit** `slowapi` `60/min` + `login 5/300s` | `aios/main.py:287` | 8/10 |
| **File validation** `validate_file` `content_type` + `size` + `ext` | `aios/core/file_validation.py` + `aios/dashboard/app.py:1829` | 8/10 |
| **Secrets** `encrypt_secret` + `encrypt_channel_config` at rest | `aios/core/secrets.py` | 8/10 |
| **Stripe webhook** `HMAC` `stripe-signature` + `idempotency` `event_id` | `aios/api/billing.py:114` | 9/10 |
| **Evolution webhook** `HMAC` `x-evolution-apikey` | `aios/api/evolution_api.py` | 8/10 |
| **S3** `aioboto3` com `endpoint` + `region` | `aios/core/storage.py:86` | 8/10 |
| **License heartbeat** `JWT 24h Ed25519` + `tamper_score` + `blacklist` | `aios/api/license.py` + `aios/core/license.py` | 9/10 (após fix `naive datetime` + `white_label` cols) |

### 🔴 Achados críticos (hardening obrigatório antes de Enterprise)

| # | Achado | CVSS | Onde | Exploração | Fix | Prazo |
|---|---|---|---|---|---|---|
| **C1** | **`select` shadowing + `db` fora de `async with` → `500` DoS em `/dashboard/evolution`** | 7.5 | `app.py:2839` | Qualquer `org` com `evolution` instance autenticado quebra dashboard (DoS) | **Fix aplicado** (revertido pra simples) — re-add com `channel_connection_id` + `db2` scope + teste `pytest` | **Feito** |
| **C2** | **`CSP` sem `blob:` bloqueava `Kokoro` `preview` `0:00` + `MEDIA_ELEMENT_ERROR`** | 6.5 | `main.py:331` | `Voice` preview 100% quebrado em produção (`AIOS_DEBUG=false`) | **Fix aplicado** (`media-src blob:` + `connect-src blob:`) | **Feito** |
| **C3** | **`kokoro-int8` `400 Unsupported model` → `500` no preview** | 5.0 | `app.py:665` `model: "kokoro-int8"` | `TTS engine` dropdown `kokoro-int8` sempre `Erro 500` | **Fix aplicado** (`model_for_api = "kokoro" if tts_model in ("kokoro","kokoro-int8")`) | **Feito** |
| **C4** | **`white_label` + `tamper_score` cols faltavam no `DB` `Coolify` → `500` em `/v1/heartbeat` + `/dashboard/evolution`** | 7.0 | `models.py` vs `DB` `postgres-38908` | `heartbeat` com `tamper` e `evolution` com `white_label` quebravam | **Fix aplicado** (`ALTER TABLE` + `models.py` cols + `naive datetime`) | **Feito** |
| **C5** | **Falta `SELECT` allow-list em `sql_query` tool — `SELECT *` sem `limit` pode exfiltrar `pg_shadow`** | 7.8 | `aios/tools/sql_query.py:21` `re.match(r"^\s*SELECT\b")` mas sem `deny` `pg_catalog` | `Analyst` com `sql_query` `SELECT * FROM pg_shadow` via `python_sandbox` bypass | **Hardening:** adicionar `deny` `pg_*, information_schema` + `row limit 100` já existe mas reforçar `where org_id` + `read-only role` no `DB` | 1 sem |
| **C6** | **`upload` `PDF` → `RAG` sem `scan` de `malware` + `size` `50k` mas `chunk 30*800=24k` pode `OOM` com `10 PDFs` paralelos | 5.5 | `app.py:1860` `files_upload` `pypdf` | `Upload 100MB PDF` com `JS bomb` → `OOM` worker `1G` | **Hardening:** limitar `10MB` + `30 chunks` já, mas adicionar `clamav` sidecar ou `validate_file` `10MB` + `_embed` com `timeout` + `queue` | 1 sem |
| **C7** | **`JWT` `HS256` com `jwt_secret` em `.env` legível `600` mas sem `rotation`** | 5.0 | `aios/config.py:34` | `leak` de `.env` via `docker inspect` → `forge JWT` | **Hardening:** `JWT` `Ed25519` já usado em `license`, migrar `auth` pra `Ed25519` + `rotation` via `CONTROL_PUBLIC_KEY` | 2 sem |
| **C8** | **`CORS` `allow_origins=["*"]` em `debug=false` mas `cors_origins=""` fallback para `app_url` — ok, mas `allow_methods=["*"]` + `allow_credentials=True` com `*` é `CORS` misconfig** | 6.0 | `main.py:344` | `Exfiltração` via `evil.com` com `credentials` | **Fix:** `allow_origins=[app_url]` já, mas explicitar `allow_methods=["GET","POST","PUT","DELETE"]` não `*` | 3 dias |
| **C9** | **`S3` `aioboto3` sem `SSE` + `versioning` → `deletion` não auditável** | 4.5 | `storage.py:100` | `Ransomware` deleta `S3` sem `versioning` | **Hardening:** habilitar `SSE-S3` + `versioning` + `object lock` no `R2/Supabase` doc | 1 sem |
| **C10** | **`Evolution API` `v2.3.7` com `AUTHENTICATION_API_KEY` em `env` mas sem `rotation` + `manager` exposto `0.0.0.0:8080` sem `IP allow`** | 6.5 | `docker-compose.coolify.yml:76` | `Brute force` `apikey` + `manager` `http://IP:8080/manager` sem `auth` forte | **Hardening:** `Coolify` `Traefik` `IPAllowList` pra `8080` + `rotate` `EVOLUTION_API_KEY` mensal | 1 sem |

### 🟡 Observações (não bloqueia, mas recomenda)

- `HSTS` só em `https` (correto) + `Secure` flag em `cookies` já via `https_only`
- `XSS` via `Jinja2 autoescape True` ok, mas `knowledge.html` `innerHTML` com `x.content.slice(0,300)` sem `DOMPurify` → `stored XSS` se `PDF` contiver `<script>` — sanitizar com `textContent` não `innerHTML`
- `audit log` já em `log_audit` mas sem `SIEM` `webhook` em `Enterprise` (já no `tracing` `usage` mas não para `audit`)
- `backup` `postgres` só `volume` `app-data`, sem `pg_dump` cron + `S3` — adicionar `deploy/backup.sh` já existe mas não `cron`

---

## 3. Decisão: Lançar como está?

**Cybersec Lead:** “**Não como Enterprise aberto, sim como Beta fechado com hardening P0 já feito.** Os 4 `P0` que achamos hoje (`evolution 500`, `CSP blob`, `kokoro-int8 400`, `white_label/tamper 500`) **já foram corrigidos em produção** (`health/live` `200`, `voice preview` `wav`, `evolution` `200` agora simples). O resto é `P1/P2` que não impede `beta` com `10 orgs` amigas, mas **impede assinar contrato `R$60k` com `BAA` sem `C5-C8` fechados.**”

**SWE Lead:** “Concordo. `Code quality` `8/10` pra MVP, `security` `7/10` após os 4 fixes de hoje. `P0` zero, `P1` 6 itens. `Enterprise` com `BAA/SLA` exige `C5` (`sql_query` deny `pg_catalog`) + `C8` (`CORS` strict) + `C10` (`Evolution` IP allow) antes de `Felipe/Patrícia` assinarem.”

**Veredito:** **Lançar `Beta Público` agora** (`Starter/Pro` com `BYOK`, `VPS` dele, `10 orgs` convidadas) **e `Enterprise Private Beta` com 3 design partners + hardening sprint 2 semanas.**

### Hardening Sprint (2 semanas) — Ordem

| Semana 1 | Semana 2 |
|---|---|
| `C5` `sql_query` deny `pg_*` + `read-only role` | `C7` `JWT` `Ed25519` rotation |
| `C8` `CORS` `allow_methods` strict | `C9` `S3` `SSE` + `versioning` doc |
| `C10` `Evolution` `IPAllowList` + `rotate key` | `C6` `upload` `10MB` + `clamav` + `XSS` `textContent` |
| Re-add `evolution analytics` com `channel_connection_id` + `db2` scope + `pytest` | `audit` `SIEM webhook` + `backup` cron `S3` |

**Métrica de saída:** `C1-C4` já `done`, `C5,C8,C10` `done` → `Enterprise` liberado. `NPS` e `pipeline R$325k` mantidos.

---

## Assinaturas

SWE Lead: _________________  Cybersec Lead: _________________  Data: 2026-09-11

Próxima revisão: 2026-09-25 (pós-hardening)

