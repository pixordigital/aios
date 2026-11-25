# CRM Schema / Truth Notes (updated 2026-11-25)

Track: CRM2 intelligence/handoff/360. No new migration and no customer-data rewrite in this fix. Typed nullable deal links already landed in `alembic/versions/schema_gaps_creds_crm_kpi.py`; model columns are `aios/db/models.py:742-747`.

## Deal <-> account/contact: typed nullable FKs exist (no FK gap)

**Current state**
- `crm_deals.account_id` and `crm_deals.contact_id` are typed, indexed, nullable FKs to `crm_accounts.id` / `crm_contacts.id` with `ON DELETE SET NULL`.
- Migration backfill copied only explicit same-org `extra_data.account_id` / `extra_data.contact_id` pointers. It did not guess from name/phone and did not rewrite ambiguous rows.
- Legacy `extra_data` mirrors remain readable for backward compatibility. New writes should use typed columns; `DEAL_EXTRA_KEYS` / `_KNOWN_EXTRA_KEYS` still block ad-hoc growth.
- Readers prefer the typed FK. Heuristic fallback (CNPJ / `lead_name` for account, email / normalized phone for contact) runs only when the typed FK is NULL. An invalid or cross-org typed FK fails closed: no heuristic fallback, no authoritative link.
- Payloads expose link `kind` / `source` / `authoritative` so typed links are distinguishable from heuristics.

**Remaining risk**
- Legacy mirrors can drift from typed columns; no automatic reconciliation here.
- Unlinked rows still depend on heuristics; ambiguous matches stay unlabeled as authoritative.

## Landed FK shape (already migrated; not re-applied)

```sql
-- crm_deals: nullable FKs, backfill done separately, old rows left untouched
ALTER TABLE crm_deals ADD COLUMN account_id VARCHAR(36) NULL;
ALTER TABLE crm_deals ADD COLUMN contact_id VARCHAR(36) NULL;

ALTER TABLE crm_deals
  ADD CONSTRAINT fk_crm_deals_account_id
  FOREIGN KEY (account_id) REFERENCES crm_accounts(id) ON DELETE SET NULL;

ALTER TABLE crm_deals
  ADD CONSTRAINT fk_crm_deals_contact_id
  FOREIGN KEY (contact_id) REFERENCES crm_contacts(id) ON DELETE SET NULL;

CREATE INDEX ix_crm_deals_account_id ON crm_deals(account_id);
CREATE INDEX ix_crm_deals_contact_id ON crm_deals(contact_id);
```

Backfill already applied (in the migration above):
1. Explicit `extra_data.account_id/contact_id` only when the target row exists in the same org.
2. No auto-backfill from CNPJ/name/email/phone guesses; those remain read-time heuristics for unlinked rows only.
3. Ambiguous rows stay NULL; human/ops review is still the only safe way to resolve them.

## Legacy extra_data flows

**Current state**
- `CrmDeal.extra_data` is legacy/tactical. `DEAL_EXTRA_KEYS` + `_KNOWN_EXTRA_KEYS` guard ad-hoc growth.
- `crm2.create_deal` blocks unknown extra_data keys.
- `crm_handoff.record_interaction` still writes legacy mirrors: `sdr_history`, `last_contacted_at`, `last_summary`, `sdr_touched` for compatibility/fast reads.
- `InteractionEvent` is the canonical interaction timeline; extra_data mirrors are not authoritative.

**Gap**
- Dual-write legacy mirrors can drift. Typed columns now separate canonical links; legacy mirrors remain only for backward compatibility.

**Safe direction (no migration in this track)**
- Avoid new extra_data writes. Keep existing mirrors only where backward compat requires.
- Label payloads: `legacy_extra_data_note`, `legacy_extra_keys`.
- Future: migrate readers to InteractionEvent/typed fields, then remove mirrors behind feature flag.

## Command center / CS workspace / Revenue Intelligence

**Current state**
- `GET /api/crm/360/overview` reports exact org-scoped `COUNT(*)` totals for deals/accounts/contacts/interactions. `recent_*` lists are samples bounded by `limit`; they are not the counts.
- `month_progress` is reused from `aios/core/sales_goals.py`: deterministic `closed_won` sum from `crm_deals` for the month, with target/status. Payload labels `source: "crm_deals.closed_won"` and states it is not finance/recognized revenue; no LLM.
- Explicitly unavailable: `cs_workspace=false`, `command_center=false`, `revenue_intelligence="minimal_heuristic_only"`, `validated_predictive_revenue_intelligence=false`.

**Gap**
- No dedicated command-center models/UI, no CS workspace objects, no validated predictive revenue model, no finance-recognition feed.
- 360 is a read-only composition over existing CRM tables; no materialized/optimized 360 read model.

**Proposed shape (future, separate track)**
- Command center: dedicated read model/projections (queue, SLA, owner load, risk), not ad-hoc joins in request path.
- CS workspace: account health timeline, playbooks, commitments, renewals; requires new models + UI.
- Revenue intelligence: keep deterministic + auditable; add a predictive model only with labeled dataset, offline eval, calibration, and explicit `validated_predictive=true` gate. Finance/recognized revenue needs a separate finance-owned source and policy decision.

## Minimal safe wiring done in this fix

- No schema migration, no customer-data rewrite, no stage/commit/deploy.
- Typed FKs preferred; heuristic links remain heuristic and only cover unlinked rows.
- Overview counts exact and org-scoped; recent lists explicitly sampled.
- Month figure deterministic from `crm_deals.closed_won`, labeled as not finance/recognized revenue.
- Read-only 360 endpoints covered by tests for labels, exact counts, tenant scope, and closed-won sum parity with `month_progress`/SQL.
- Extra-data writes not expanded; legacy mirrors remain only where already present.
