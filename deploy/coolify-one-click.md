# AIOS — Coolify 1-Click

## Por que concentrar no Coolify?
Frente direto na VPS (nginx manual + systemd + certbot) funciona, mas Coolify já faz: Traefik SSL auto, healthchecks, rollback, logs, env criptografado, deploy por git push. 1 stack, 1 painel.

## Deploy 1-Click

### Opção A — Raw Compose (30s)
1. Coolify → **New Resource → Docker Compose (Raw Compose Deployment)**
2. Cole conteúdo de `docker-compose.coolify.one-click.yml`
3. Set `AIOS_APP_URL=https://seu-dominio.com`
4. Clique **Generate** em:
   - `AIOS_JWT_SECRET` → `openssl rand -hex 32`
   - `POSTGRES_PASSWORD` / `REDIS_PASSWORD` → `openssl rand -hex 16`
5. Opcional: `AIOS_OPENROUTER_API_KEY`, Stripe, SMTP
6. Deploy → Coolify cria `postgres+redis+otel+app+worker` + SSL Traefik automático

### Opção B — Git (recomendado)
1. Coolify → **New Resource → Docker Compose → Git Repository** → `pixor_aios`
2. Compose file: `docker-compose.coolify.one-click.yml`
3. Set envs no painel Coolify (mesmo acima)
4. Deploy

## Variáveis obrigatórias
```
AIOS_APP_URL=https://aios.seudominio.com
AIOS_JWT_SECRET=<64 hex>
POSTGRES_PASSWORD=<senha>
REDIS_PASSWORD=<senha>
```
Opcionais mas recomendadas: `AIOS_OPENROUTER_API_KEY`, `AIOS_S3_*` (Supabase/R2), `AIOS_STRIPE_*`

## Pós-deploy (auto)
- Migrations rodam em `init_db()` no startup
- Health: `https://.../health/ready` (Coolify já monitora)
- Logs: Coolify → Service → Logs
- Scale worker: Coolify → Service → worker → Replicas 3

## Migração do deploy manual
1. `pg_dump` da VPS antiga → import no Coolify postgres
2. `rsync -av ./data/ coolify:/data/`
3. Apontar DNS para Coolify Traefik
4. Desligar nginx/systemd antigo
