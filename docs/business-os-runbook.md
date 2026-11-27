# Business OS — Runbook Operacional

Escopo: guia mínimo para rodar o AIOS como “Business OS” com mínima interferência humana, **sem automação falsa**. Cada automação deve ter dono humano, limite claro e evidência auditável.

## Onboarding

Checklist de entrada (concluir antes de expor para operação real):

- [ ] **Dono humano definido**: responsável final pela operação, aprovações e incidentes.
- [ ] **Organização/tenant criado**: org, usuários e agentes cadastrados no ambiente correto.
- [ ] **Configuração validada**: variáveis de ambiente, segredos e integrações revisados; nada hardcoded.
- [ ] **Limites reais confirmados**: planos/quotas conferidos no código (`aios/config.py:PLANS`, `aios/core/limits.py:check_org_limits`); não prometer limite inexistente.
- [ ] **HITL configurado**: ações sensíveis com aprovação humana (`approval_required`/fluxos de aprovação) antes de produção.
- [ ] **Canais e integrações testados**: WhatsApp/Slack/email/API apenas com credenciais reais e smoke test.
- [ ] **Backup/restore testado**: pelo menos um restore de validação em ambiente seguro.
- [ ] **Runbook acessível**: equipe sabe onde está este documento e quem acionar.

## Configuração necessária

| Item | Onde/config | Nota |
|---|---|---|
| Banco de dados | `AIOS_DATABASE_URL` / deploy env | Migrações via Alembic; confirmar head antes de deploy. |
| Redis | `REDIS_URL` | Filas, cache e coordenação. |
| Segredos | Secret manager / env do deploy | Nunca commitar segredos; rotacionar conforme política. Scaffold: `docs/SECRETS_KMS_ROTATION_SCAFFOLD.md`. |
| Auth/JWT | Config de auth/JWT do AIOS | Revisar chaves, expiração e papéis. |
| Planos/limites | `aios/config.py`, `aios/core/limits.py` | Fonte de verdade; UI/docs não podem divergir. |
| Observabilidade | Logs, health checks, métricas | `/health/ready` e logs do app/worker antes de declarar saudável. |
| Integrações | Credenciais por integração | Escopo mínimo; validar permissões e webhooks. |

## Permissões e papéis

- **Princípio do menor privilégio**: cada usuário/agente recebe apenas o acesso necessário.
- **Papéis**: separar operação, administração e auditoria quando possível; mudanças sensíveis exigem papel autorizado.
- **Aprovações HITL**: ações com efeito externo/irreversível (envio, pagamento, exclusão, publicação, mudança de infra) devem ter aprovação humana rastreável.
- **Rastreabilidade**: toda ação automática relevante deve registrar quem/quando/o quê/resultado; sem log, sem autonomia.
- **Revisão periódica**: revisar acessos, chaves e integrações ativas; remover o que não é usado.

## Backup e restore

### Backup

- Usar scripts/deploy existentes como base: `scripts/backup-cron.sh`, `scripts/backup.sh`, `deploy/backup.sh`, `deploy/aios-backup.service`, `deploy/aios-backup.timer`.
- Incluir: banco Postgres (`pg_dump`), arquivos/config críticos e segredos **referenciados** (não copiar segredo para lugar inseguro).
- Definir retenção e destino (local + offsite/S3 quando configurado).
- Registrar data, checksum/tamanho e resultado do backup.
- Verificar backup não-vazio: `gzip -t` + tamanho mínimo; `deploy/backup.sh` já falha em dump vazio.

### Restore drill (obrigatório, ambiente isolado)

Nunca restaurar drill em produção. Exigir aprovação humana e alvo descartável.

**Script automatizado (preferido):** `deploy/restore_drill.sh`

```bash
# Postgres (alvo isolado; nome deve conter drill/restore_test/tmp_restore/smoke_restore)
AIOS_RESTORE_DRILL_TARGET_URL='postgresql://user:pass@localhost:5432/aios_restore_drill' \
AIOS_RESTORE_DRILL_CONFIRM=I_UNDERSTAND_THIS_IS_ISOLATED \
deploy/restore_drill.sh /data/backups/aios_YYYYMMDD_HHMMSS.sql.gz \
  --report /tmp/restore-drill-evidence.json

# SQLite smoke (temp-only, sem psql/pg_dump)
AIOS_RESTORE_DRILL_TARGET_URL='sqlite:///./tmp_restore_drill.db' \
AIOS_RESTORE_DRILL_CONFIRM=I_UNDERSTAND_THIS_IS_ISOLATED \
deploy/restore_drill.sh /path/to/backup.sqlite.gz --report /tmp/restore-drill-evidence.json
```

**Fail-closed:** script recusa alvo ausente, confirmação ausente, alvo igual a `AIOS_DATABASE_URL/DATABASE_URL`, nome/path sem marcador de drill, ou alvo prod-like.

**Passos manuais (fallback):**
1. **Selecionar artefato**: backup recente + checksum/SHA256 + tamanho/mtime.
2. **Integridade**: `sha256sum <backup.sql.gz>` e `gzip -t <backup.sql.gz>`.
3. **Restaurar isolado**: criar DB descartável; `gunzip -c ... | psql ...` ou `pg_restore` conforme formato.
4. **Migração**: `AIOS_DATABASE_URL=<restore> .venv/bin/alembic upgrade head` e `alembic current`.
5. **Smoke**: `/health/ready` equivalente/app boot, login, tabelas críticas, contagens básicas.
6. **Validar dados**: orgs/users/agents/conversations/messages/audit_logs; spot-check registros recentes; isolamento por org.
7. **Evidência**: operador, horário UTC, artefato, checksum, duração restore, resultado migração/smoke, RPO/RTO observados, issues, sign-off.
8. **Cleanup**: dropar DB descartável.

**Evidence checklist (anexar ao ticket/change):**
- [ ] Artefato: caminho, SHA256, tamanho, mtime/idade (RPO observado).
- [ ] Alvo isolado: URL redigida/tipo, confirmação humana, não-produto.
- [ ] Restore: status, duração (RTO observado), log/erros.
- [ ] Integridade: `gzip -t`/`pg_restore --list`/`PRAGMA integrity_check` conforme formato.
- [ ] Migração: `alembic current`/head esperado (Postgres).
- [ ] Smoke: tabelas críticas presentes, contagens básicas, `/health/ready` ou boot equivalente.
- [ ] Spot-check: registros recentes, isolamento por org/tenant.
- [ ] Cleanup: alvo descartável removido.
- [ ] Sign-off: operador + responsável humano.

Comandos de referência: `docs/SECURITY_RELIABILITY_HARDENING.md`.

### Restore de produção (human-gated)

1. Declarar incidente/mudança e acionar dono humano.
2. Escolher snapshot/backup válido e verificar integridade.
3. Restaurar em ambiente isolado primeiro quando possível.
4. Aplicar migrações necessárias (`alembic upgrade head`) conforme estado do backup.
5. Validar: `/health/ready`, login, dados críticos, integrações e filas.
6. Somente após validação, promover para produção.
7. Registrar RPO/RTO observados e lições aprendidas.

## Deploy e operação

- **Pré-deploy**: `git status` limpo no escopo, testes relevantes passando, migração revisada, plano de rollback.
- **Deploy**: seguir runbook de deploy do ambiente (`docs/DEPLOY.md`, Coolify/compose conforme stack). Não improvisar em produção.
- **Pós-deploy smoke**: health ready, login/dashboard, endpoint crítico, worker/filas, logs sem erro novo.
- **Rollback**: ter imagem/commit anterior identificado; rollback de schema só com plano compatível e backup.
- **Mudanças de config**: tratar segredo/config como mudança auditada; nunca expor valor em chat/log.

## LGPD / privacidade operacional

- Scaffold operacional (templates/checklists, human-gated): `docs/LGPD_COMPLIANCE_SCAFFOLD.md`.
- Antes de tratar dado pessoal em produção: preencher data map, base legal, DPO/owner, retenção, rota DSAR, revisão legal. Sem alegação de certificação.
- Incidente com dado pessoal: seguir seção de incidente abaixo + [`docs/SECURITY_LGPD_COMPLIANCE.md`](./SECURITY_LGPD_COMPLIANCE.md) (checklist de handoff privacy/legal, signoff, evidência). **[HUMAN-GATED]** decisão de notificação.

## LGPD/compliance scaffold

- Template operacional (docs-only, sem certificação legal): [`docs/SECURITY_LGPD_COMPLIANCE.md`](./SECURITY_LGPD_COMPLIANCE.md).
- Cobertura: data map, DPO/owner checklist, base legal, DSAR/export/delete, retenção, incidente/signoff legal.
- Hardening/restore: [`docs/SECURITY_RELIABILITY_HARDENING.md`](./SECURITY_RELIABILITY_HARDENING.md). Limites legais: [`docs/business-os-legal-boundaries.md`](./business-os-legal-boundaries.md).
- Qualquer ação com dado real/prod, notificação, exclusão, exportação sujeita a exceção legal, ou interpretação jurídica exige dono humano + revisão qualificada.

## Incidente e suporte

### Classificação

- **Sev1**: indisponibilidade, perda de dados, risco de segurança. Acionar dono humano imediatamente.
- **Sev2**: função crítica degradada, fila parada, integração principal falhando.
- **Sev3**: bug não crítico, degradação parcial, dúvida operacional.

### Resposta

1. **Conter**: pausar automação afetada, desativar integração ou colocar em modo seguro/HITL.
2. **Diagnosticar**: logs, health, deploy recente, filas, DB, integrações externas.
3. **Comunicar**: status, impacto, ETA/next update; sem prometer correção sem evidência.
4. **Recuperar**: rollback, restore, hotfix ou workaround aprovado.
5. **Pós-incidente**: causa raiz, ação corretiva, teste/regressão, atualização deste runbook.

### Suporte

- Canal de suporte interno definido pelo dono humano.
- Registrar ticket com: horário, impacto, passos, logs, hipótese, ação tomada.
- Não executar ação destrutiva sem confirmação humana e backup/rollback conhecido.

## Humano responsável

- Toda operação Business OS tem um **humano responsável** (owner) nomeado e alcançável.
- O humano responsável aprova: go-live, mudanças de permissão, integrações novas, ações destrutivas, restore de produção e exceções de HITL.
- Agentes podem executar tarefas operacionais, mas **não transferem responsabilidade**. Em dúvida, pausar e escalar para o humano responsável.
- Decisões de risco devem ser registradas com contexto, evidência e resultado.
