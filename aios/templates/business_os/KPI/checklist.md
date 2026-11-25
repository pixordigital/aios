# KPI — Checklist de medição

Defina fonte e cadência a partir desta checklist antes de registrar um valor.

- [ ] `sold_qty` — De onde: `CrmDeal`/sales com `closed_won`, última semana. Frequência: semanal.
- [ ] `sold_value_brl` — De onde: soma `won_amount` (BRL) dos deals closed won. Frequência: semanal.
- [ ] `new_clients` — De onde: `CrmAccount` criados recentemente, ou primeira compra confirmada. Frequência: semanal.
- [ ] `happy_clients_pct` — De onde: pesquisa de satisfação/feedback (custo zero: perguntar aos clientes); sem base, reportar `not_instrumented` conforme `aios/governance/kpi.py`. Frequência: semanal.
- [ ] `tickets_closed` — De onde: ticket desk/suporte com status fechado. Frequência: semanal.
- [ ] `sale_time_day` — De onde: `closed_won` − `created_at` em dias, média dos deals do período. Frequência: semanal.

Regra: sem dados, use `unknown`/`not_instrumented` — nunca valor sintético.
