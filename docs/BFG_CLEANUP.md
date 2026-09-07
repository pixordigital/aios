# Guia BFG — Limpeza de Histórico Git (Secrets Vazados)

## Contexto

O repositório **pixordigital/aios** está **PUBLIC** (`gh repo view --json isPrivate` → `false`). O histórico contém secrets rotacionados que **precisam ser removidos do git log** antes do lançamento público.

### Secrets no histórico (rotacionados, mas ainda no log)

| Secret | Valor antigo (vazado) | Valor novo (rotacionado) |
|--------|----------------------|-------------------------|
| `POSTGRES_PASSWORD` | `460a074...` | `76408bc423087feedc9d96e59d6782e4` |
| `REDIS_PASSWORD` | `a74de8...` | `eefc34b85ae3916e10c9cda4a2ea3172` |
| `JWT_SECRET` | `d9f36b4...` | `a473fa14d64aa2ef764424f4c36482a2e22ba716cface98d7f2e3b47511f7556` |
| `ADMIN_MASTER_KEY` | (vazado) | `2596637c399db3461d35875e7b207e0b3eb61f2f040cc1544d8ca74d02b6d902` |

**Commit seguro base:** `f328da5` (primeiro commit sem secrets no código atual)

---

## Opção A — BFG Repo-Cleaner (recomendado, mais rápido)

### 1. Instalar BFG
```bash
# macOS
brew install bfg

# Linux (Java necessário)
wget https://repo1.maven.org/maven2/com/madgag/bfg/1.14.0/bfg-1.14.0.jar
alias bfg="java -jar ~/bfg-1.14.0.jar"
```

### 2. Criar arquivo de padrões (`patterns.txt`)
```text
# Senhas reais (substitua pelos valores reais vazados do seu .env antigo)
460a074
a74de8
d9f36b4
2596637c399db3461d35875e7b207e0b3eb61f2f040cc1544d8ca74d02b6d902
eefc34b85ae3916e10c9cda4a2ea3172
```

### 3. Clonar repo **mirror** (bare, sem working tree)
```bash
git clone --mirror git@github.com:pixordigital/aios.git aios.git
cd aios.git
```

### 4. Rodar BFG (apaga dos blobs, não reescreve commits)
```bash
# Substituir secrets por ***REMOVED***
bfg --replace-text ../patterns.txt --no-blob-protection

# Ou apagar arquivos inteiros se preferir
# bfg --delete-files ".env" --delete-files "*.env" --no-blob-protection
```

### 5. Limpar refs órfãos e compactar
```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### 6. Forçar push (reescreve histórico no GitHub)
```bash
git push --force --all
git push --force --tags
```

### 7. Verificar
```bash
# Confirmar que secrets não aparecem mais
git log --all --oneline --grep="460a074\|a74de8\|d9f36b4\|2596637c" | head -5
# Deve retornar vazio
```

---

## Opção B — git filter-repo (nativo, sem Java)

### 1. Instalar
```bash
pip install git-filter-repo
```

### 2. Clonar mirror
```bash
git clone --mirror git@github.com:pixordigital/aios.git aios.git
cd aios.git
```

### 3. Rodar filter-repo com callbacks Python
```bash
git filter-repo \
  --replace-text ../patterns.txt \
  --force
```

### 4. Push forçado
```bash
git push --force --all
git push --force --tags
```

---

## Opção C — Novo remote limpo (mais seguro, sem reescrever histórico)

Se não quiser reescrever histórico do repo original:

### 1. Criar branch limpa a partir de `f328da5`
```bash
git fetch origin
git checkout f328da5 -b clean-main
```

### 2. Verificar que não há secrets no código atual
```bash
# grep por padrões de secret no working tree
grep -r "460a074\|a74de8\|d9f36b4\|2596637c\|eefc34b" . --exclude-dir=.git
# Deve retornar vazio
```

### 3. Criar novo repositório no GitHub
```bash
# Via gh CLI
gh repo create pixordigital/aios-clean --public --description "AIOS — Orquestração de agentes IA (histórico limpo)"
```

### 4. Push da branch limpa como main
```bash
git remote add clean-origin git@github.com:pixordigital/aios-clean.git
git push clean-origin clean-main:main
```

### 5. Arquivar repo antigo / redirecionar
- No GitHub: Settings → General → "Archive this repository" no repo antigo
- Update README do repo antigo apontando para o novo
- Atualizar Coolify/Deploy para apontar para `aios-clean`

---

## Pós-limpeza (obrigatório em todas as opções)

### 1. Rotacionar **todos** os secrets novamente
Mesmo após limpar histórico, os valores antigos circularam. Gere novos:

```bash
# JWT secret (256 bits)
openssl rand -hex 32

# Admin master key
openssl rand -hex 32

# Postgres password
openssl rand -base64 24

# Redis password
openssl rand -base64 24
```

### 2. Atualizar no Coolify / .env de produção
- Settings → Environment Variables no Coolify
- Redeploy forçado (`force_rebuild: true`)

### 3. Revogar tokens GitHub / CI que possam ter vazado
- GitHub: Settings → Developer settings → Personal access tokens
- CI: Rotacionar `GITHUB_TOKEN` se usado em logs

### 4. Habilitar secret scanning no repo novo
```bash
gh api -X PUT repos/pixordigital/aios-clean/secret-scanning/alerts -f secret_scanning_enabled=true
gh api -X PUT repos/pixordigital/aios-clean/secret-scanning/push-protection -f push_protection_enabled=true
```

### 5. Adicionar Gitleaks no CI (já feito em `.github/workflows/ci.yml`)
```yaml
gitleaks:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with: { fetch-depth: 0 }
    - uses: gitleaks/gitleaks-action@v2
```

---

## Checklist de validação

- [ ] `git log --all --grep="SECRET_OLD" ` retorna vazio
- [ ] `gh repo view pixordigital/aios --json isPrivate` → `true` (repo privado) OU repo novo `aios-clean` é o canonical
- [ ] Coolify deploya com secrets novos (health check `/health` → `live:true ready:true db:ok`)
- [ ] CI gitleaks passa (build verde)
- [ ] `.env` de produção atualizado com secrets novos
- [ ] Documentado no changelog / release notes: "Histórico reescrito para remover secrets vazados"

---

## Referências

- BFG: https://rtyley.github.io/bfg-repo-cleaner/
- git-filter-repo: https://github.com/newren/git-filter-repo
- GitHub secret scanning: https://docs.github.com/en/code-security/secret-scanning
- Coolify env vars: https://coolify.io/docs/knowledge-base/environment-variables