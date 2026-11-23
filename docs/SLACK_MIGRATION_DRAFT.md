# Slack Migration Map — DRAFT (AIOS mutations: none)

Workspace: Pixor (`T0C5A8G1B42`, https://pixorworkspace.slack.com/)
Inventory: first 2026-11-22; re-verified 2026-11-23 (read-only `conversations.list`, user token `pixordigital`).
Coverage: public+private channels, users. No app/integration/admin UI audit.
Gate: `GET /api/slack/migration-gate` requires `slack_workspace_inventoried`, `slack_migration_map_approved`, Founder. **BLOCKED.**

## Inventory
### Channels (36 total, 0 private, 32 active, 4 archived)
Observed workspace changes since first inventory — renames: `general`→`company-announcements` (C0C5A8GE1BL), `dev`→`dept-engineering` (C0C57KKKNG3), `sales`→`dept-sales` (C0C5DLK8VUH), `random`→`org-random-legacy` (C0C64P7RV0Q). Archived: `blue-team` (C0C5BUFTY30), `red-team` (C0C5HH2F8JY), `aios` (C0C64PCQHLG), `__scope_probe__` (C0CKZRJPD6E). Created: 29 taxonomy channels (2026-11-22). AIOS performed none of these mutations.

| id | current name | state | note |
|---|---|---|---|
| C0C5A8GE1BL | company-announcements | active | renamed from `general` |
| C0C57KKKNG3 | dept-engineering | active | renamed from `dev` |
| C0C5DLK8VUH | dept-sales | active | renamed from `sales` |
| C0C64P7RV0Q | org-random-legacy | active | renamed from `random` |
| C0C5BUFTY30 | blue-team | archived | was REVIEW → archived |
| C0C5HH2F8JY | red-team | archived | was REVIEW → archived |
| C0C64PCQHLG | aios | archived | was REVIEW → archived |
| C0CKZRJPD6E | __scope_probe__ | archived | probe artifact |

### Users (3, non-deleted)
| id | name | real | bot | admin |
|---|---|---|:---:|:---:|
| USLACKBOT | slackbot | Slackbot | no | no |
| U0C55DZPDKP | aios2 | AIOS | yes | no |
| U0C64P7ARCG | pixordigital | Bernardo | no | yes |

## Taxonomy status (32/32 active channels represented)
AIOS taxonomy mirrors active Slack channels; 4 archived excluded. Restricted governance present: security-incidents, security-monitoring, privacy-governance, privacy-incidents. Projects present: project-showcar-pilot, project-aios-product, project-lia-launch.

## System of record (AIOS)
discussions=slack; tasks=aios_ocp; approvals=aios_decision_approval; customer_information=aios_crm; documents=aios_knowledge; kpis=aios_organizational_intelligence; process_execution=aios_process_workflow_engines; skills=aios_skills

## Required before any mutation
1. Founder reviews/edits per-channel action and approves map.
2. Set AIOS gate metadata only via approved process: `slack_workspace_inventoried=true`, `slack_migration_map_approved=true`, Founder identity.
3. Apply controlled batches only after explicit per-batch confirmation; verify membership/rename; no agent channels.
4. Admin UI review: apps/integrations/retention/sensitive data not fully API-visible.

## Status
DRAFT ONLY. NO AIOS SLACK MUTATIONS EXECUTED. Workspace renames/archives/creations observed externally and recorded above. Migration gate remains BLOCKED; Founder approval not evidenced by channel state. `/dashboard/channels` lists AIOS `ChannelConnection` rows, not Slack workspace channels — it cannot reflect workspace changes without a Slack sync (production has no `SLACK_USER_TOKEN`).
