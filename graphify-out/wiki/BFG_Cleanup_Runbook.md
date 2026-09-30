# BFG Cleanup Runbook

> 36 nodes · cohesion 0.06

## Key Concepts

- **Guia BFG — Limpeza de Histórico Git (Secrets Vazados)** (8 connections) — `docs/BFG_CLEANUP.md`
- **Opção A — BFG Repo-Cleaner (recomendado, mais rápido)** (8 connections) — `docs/BFG_CLEANUP.md`
- **Opção C — Novo remote limpo (mais seguro, sem reescrever histórico)** (6 connections) — `docs/BFG_CLEANUP.md`
- **Pós-limpeza (obrigatório em todas as opções)** (6 connections) — `docs/BFG_CLEANUP.md`
- **Opção B — git filter-repo (nativo, sem Java)** (5 connections) — `docs/BFG_CLEANUP.md`
- **Rotação de Secrets — AIOS** (4 connections) — `docs/SECRET_ROTATION.md`
- **BFG_CLEANUP.md** (2 connections) — `docs/BFG_CLEANUP.md`
- **Contexto** (2 connections) — `docs/BFG_CLEANUP.md`
- **SECRET_ROTATION.md** (2 connections) — `docs/SECRET_ROTATION.md`
- **1. Criar branch limpa a partir de `f328da5`** (1 connections) — `docs/BFG_CLEANUP.md`
- **1. Instalar** (1 connections) — `docs/BFG_CLEANUP.md`
- **1. Instalar BFG** (1 connections) — `docs/BFG_CLEANUP.md`
- **1. Rotacionar **todos** os secrets novamente** (1 connections) — `docs/BFG_CLEANUP.md`
- **2. Atualizar no Coolify / .env de produção** (1 connections) — `docs/BFG_CLEANUP.md`
- **2. Clonar mirror** (1 connections) — `docs/BFG_CLEANUP.md`
- **2. Criar arquivo de padrões (`patterns.txt`)** (1 connections) — `docs/BFG_CLEANUP.md`
- **2. Verificar que não há secrets no código atual** (1 connections) — `docs/BFG_CLEANUP.md`
- **3. Clonar repo **mirror** (bare, sem working tree)** (1 connections) — `docs/BFG_CLEANUP.md`
- **3. Criar novo repositório no GitHub** (1 connections) — `docs/BFG_CLEANUP.md`
- **3. Revogar tokens GitHub / CI que possam ter vazado** (1 connections) — `docs/BFG_CLEANUP.md`
- **3. Rodar filter-repo com callbacks Python** (1 connections) — `docs/BFG_CLEANUP.md`
- **4. Habilitar secret scanning no repo novo** (1 connections) — `docs/BFG_CLEANUP.md`
- **4. Push da branch limpa como main** (1 connections) — `docs/BFG_CLEANUP.md`
- **4. Push forçado** (1 connections) — `docs/BFG_CLEANUP.md`
- **4. Rodar BFG (apaga dos blobs, não reescreve commits)** (1 connections) — `docs/BFG_CLEANUP.md`
- *... and 11 more nodes in this community*

## Relationships

- No strong cross-community connections detected

## Source Files

- `docs/BFG_CLEANUP.md`
- `docs/SECRET_ROTATION.md`

## Audit Trail

- EXTRACTED: 34 (97%)
- INFERRED: 1 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*