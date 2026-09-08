# Rotação de Secrets — AIOS

Sempre que `AIOS_JWT_SECRET`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `LIVEKIT_API_SECRET` estiverem como `changeme` ou vazios, rotacione **imediatamente** no Coolify.

## Coolify (produção 178.105.181.38)

1. Coolify → `pixor-aios` → Environment (JWT/LIVEKIT sem downtime)
   ```
   AIOS_JWT_SECRET=$(openssl rand -hex 32)
   AIOS_LIVEKIT_API_SECRET=$(openssl rand -hex 32)
   AIOS_ADMIN_MASTER_KEY=$(openssl rand -hex 32)
   ```
   Save → Redeploy (sem cache) — app/worker reiniciam, JWT antigos invalidam (avisar usuários re-login)

2. Postgres/Redis sem downtime (opcional, com janela):
   ```bash
   # no VPS, sem perder dados:
   docker exec postgres-38908ddf psql -U postgres -c "ALTER USER aios WITH PASSWORD 'NOVO_HEX16';"
   # atualize Coolify Environment POSTGRES_PASSWORD=NOVO_HEX16, REDIS_PASSWORD=NOVO
   docker exec redis-38908ddf redis-cli -a oldpass CONFIG SET requirepass NOVO
   # Save → Redeploy (postgres/redis recriam com novo pass mas volume mantém dados)
   ```
3. VPS: `docker exec postgres-... psql -U aios -c "SELECT version_num FROM alembic_version;"` — deve estar `c9a1b2c3d4e6`
4. Teste `curl -s https://.../health/ready` → `ready`

## BFG (se secret caiu no git)

```bash
# ver leak
gitleaks detect --source . --verbose
# limpar histórico (local)
bfg --delete-files .env --delete-text "changeme" --replace-text passwords.txt
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force origin main
```

## Checklist pós-rotação

- [ ] `docker ps` — app/worker `healthy`
- [ ] `/health` → `rag.fallback==false` (pgvector ok)
- [ ] Invite `POST /dashboard/members/invite` → 403 após 10/dia (rate-limit)
- [ ] Login sem `email_verified` → 403 "Verifique seu e-mail" quando `AIOS_REGISTRATION_ENABLED=false`
- [ ] LiveKit — `wss://...` com secret novo, voice `profiles: ["voice"]` só quando necessário
