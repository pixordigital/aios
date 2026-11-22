# CRM Schema Gaps (2026-11-22)

Track: CRM2 intelligence/handoff/360. No schema migrations applied in this track.

## Gap: deal <-> account/contact has no schema FK

**Current state**
- `crm_deals` has no `account_id` / `contact_id` FK columns.
- `crm_accounts`, `crm_contacts`, `crm_interactions` exist (tables/migrations present), but deal linkage is inferred at read time.
- Inference lives in `aios/core/crm_intelligence.py`: `find_account_for_deal`, `find_contact_for_deal`.
- Heuristic order:
  - Account: `deal.extra_data.account_id` (legacy pointer) -> `extra_data.cnpj` exact -> `lead_name` exact name match.
  - Contact: `deal.extra_data.contact_id` (legacy pointer) -> `lead_email` exact -> normalized phone digit match scan.
- API/UI label these as heuristic/inferred; they are not authoritative relational integrity.

**Why it matters**
- No DB-enforced integrity or cascade semantics for deal ownership.
- Name/phone heuristics can mislink; ambiguity is silent without provenance.
- Duplicate/merge/account merges need deterministic identity.

## Proposed FK/migration shape (NOT applied)

Minimal safe schema evolution, future migration:

```sql
-- crm_deals: add nullable FKs first (backfill, then tighten policy separately)
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

Backfill plan (separate data migration/script, audited):
1. Resolve by explicit `extra_data.account_id/contact_id` only when row exists in same org.
2. Resolve by strong identifiers: account CNPJ exact; contact email exact.
3. Do **not** auto-backfill ambiguous name/phone matches; emit report for human/ops review.
4. Write `CrmDealVersion`/audit record for each backfill with provenance `{"source":"backfill","rule":...}`.
5. After backfill confidence, keep heuristic read fallback only for legacy/unlinked rows; expose `link_source`.

Model/API follow-up after migration:
- Add `CrmDeal.account_id/contact_id` mapped columns + relationships.
- Prefer FK over heuristic; heuristic fallback read-only, explicitly labeled.
- Block new ad-hoc `extra_data.account_id/contact_id` writes; write typed columns.
- Add tenant-scoped integrity tests and ambiguity-report tests.

## Legacy extra_data flows

**Current state**
- `CrmDeal.extra_data` is legacy/tactical. `DEAL_EXTRA_KEYS` + `_KNOWN_EXTRA_KEYS` guard ad-hoc growth.
- `crm2.create_deal` blocks unknown extra_data keys.
- `crm_handoff.record_interaction` still writes legacy mirrors: `sdr_history`, `last_contacted_at`, `last_summary`, `sdr_touched` for compatibility/fast reads.
- `InteractionEvent` is canonical interaction timeline; extra_data mirrors are not authoritative.

**Gap**
- Dual-write legacy mirrors can drift from canonical timeline.
- No schema-level separation of tactical extra_data vs canonical relations.

**Safe direction (no migration in this track)**
- Avoid adding new extra_data writes. Keep existing mirrors only where backward compat requires.
- Label payloads: `legacy_extra_data_note`, `legacy_extra_keys`.
- Future: migrate readers to InteractionEvent/typed fields, then remove mirrors behind feature flag.

## Command center / CS workspace / Revenue Intelligence

**Current state**
- `GET /api/crm/360/overview` exposes minimal read model: deals/accounts/contacts/interactions counts + recent items.
- Explicitly unavailable: `cs_workspace=false`, `command_center=false`, `revenue_intelligence="minimal_heuristic_only"`.
- Prioritization is deterministic heuristic, not validated predictive.

**Gap**
- No dedicated command-center models/UI, no CS workspace objects, no validated predictive revenue model.
- 360 is read-only composition over existing CRM tables; no materialized/optimized 360 read model.

**Proposed shape (future, separate track)**
- Command center: dedicated read model/projections (queue, SLA, owner load, risk), not ad-hoc joins in request path.
- CS workspace: account health timeline, playbooks, commitments, renewals; requires new models + UI.
- Revenue intelligence: start deterministic + auditable features; only add predictive model with labeled dataset, offline eval, calibration, and explicit `validated_predictive=true` gate.

## Minimal safe wiring done in this track

- No schema migrations.
- No fake FK. Heuristic links remain heuristic.
- API payloads expose explicit link provenance/heuristic labels.
- Read-only 360 endpoints covered by tests for labels and tenant scope.
- Extra-data writes not expanded; legacy mirrors remain only where already present.