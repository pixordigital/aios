# PRINCÍPIO INEGOCIÁVEL — AIOS

**Data:** 2026-09-13
**Origem:** Decisão do fundador — "Opção A, sempre usamos a verdade e realidade no AIOS, nunca jamais inventamos ou mentimos pro cliente... salva isso pra nunca mais esquecer"

## Regra

**No AIOS, nunca inventamos ou mentimos pro cliente. Sempre usamos a verdade e a realidade.**

- Números na home, pricing, docs e dashboard DEVEM refletir limites reais do código (`aios/config.py:PLANS` + `aios/core/limits.py`).
- Se um limite não existe no código (ex: `voice_minutes` não existe em `PLANS`/`UsageRecord`/`check_org_limits`), **não prometer** na home.
- Usar `~` e `*estimativa` quando for projeção (ex: `500 msgs/dia ~500 conversas`).
- Todo número novo na home/docs deve ter `grep` no código provando que é `enforced` ou marcado como `*estimativa`.

## Check (antes de cada deploy da home)

```bash
grep -rn "min voz\|msgs/dia" website/index.html
grep -A2 "PLANS\[" aios/config.py
grep -n "max_messages_per_day\|max_tokens_per_month\|max_cost_brl" aios/core/limits.py
# Se não bater, não deploy.
```

**Quebrar esta regra = churn + processo + perda de confiança. Não negociável.**

**Fix aplicado:** 2026-09-13 — trocado `10k min voz` (fake, não enforced) → `500 msgs/dia + 5M tokens/mês` (reais, enforced em `check_org_limits`).

**Assinatura fundador:** _________________  Data: 2026-09-13
