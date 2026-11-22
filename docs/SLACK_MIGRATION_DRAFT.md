# Slack Migration Map — DRAFT (no mutations performed)

Workspace: Pixor (`T0C5A8G1B42`, https://pixorworkspace.slack.com/)
Inventory date: 2026-11-22 (read-only, user token `pixordigital`).
Coverage: public+private channels, users. No app/integration/admin UI audit.
Gate: `GET /api/slack/migration-gate` requires `slack_workspace_inventoried`, `slack_migration_map_approved`, Founder. **BLOCKED.**

## Inventory
### Channels (7 total, 0 private, 0 archived)
| id | name | private | members | member | proposed action | target | owner | approval |
|---|---|:---:|---:|:---:|---|---|---|---|
| C0C5A8GE1BL | general | no | 1 | yes | KEEP/REMAP | keep or `company-announcements` (confirm Slack default rename constraint) | Founder | REQUIRED |
| C0C57KKKNG3 | dev | no | 2 | yes | MAP | `dept-engineering` | Eng lead | REQUIRED |
| C0C5BUFTY30 | blue-team | no | 2 | yes | REVIEW | `security-monitoring` or archive | Security | REQUIRED |
| C0C5HH2F8JY | red-team | no | 2 | yes | REVIEW | restricted `security-incidents`/project; inspect sensitivity | Security/Founder | REQUIRED |
| C0C5DLK8VUH | sales | no | 2 | yes | MAP | `dept-sales` | Sales lead | REQUIRED |
| C0C64P7RV0Q | random | no | 0 | no | REVIEW | archive or keep | Founder | REQUIRED |
| C0C64PCQHLG | aios | no | 0 | no | REVIEW | `project-aios-product` or archive | Founder | REQUIRED |

### Users (3, non-deleted)
| id | name | real | bot | admin |
|---|---|---|:---:|:---:|
| USLACKBOT | slackbot | Slackbot | no | no |
| U0C55DZPDKP | aios2 | AIOS | yes | no |
| U0C64P7ARCG | pixordigital | Bernardo | no | yes |

## Taxonomy gaps (proposed, not created)
Leadership: company-announcements, founder-office, leadership, company-decisions, company-performance
Departments: dept-sales, dept-lia, dept-media-growth, dept-data, dept-product, dept-engineering, dept-operations, dept-security, dept-privacy-lgpd, dept-finance
Cross-functional: collab-sales-lia, collab-sales-data, collab-media-data, collab-product-engineering, collab-privacy-security, collab-revenue-operations
Org systems: org-process-improvement, org-skills, org-experiments, org-innovation-learning, org-kpi-analytics
Restricted governance: security-incidents, security-monitoring, privacy-governance, privacy-incidents
Projects: project-showcar-pilot, project-aios-product, project-lia-launch

## System of record (AIOS)
discussions=slack; tasks=aios_ocp; approvals=aios_decision_approval; customer_information=aios_crm; documents=aios_knowledge; kpis=aios_organizational_intelligence; process_execution=aios_process_workflow_engines; skills=aios_skills

## Required before any mutation
1. Founder reviews/edits per-channel action and approves map.
2. Set AIOS gate metadata only via approved process: `slack_workspace_inventoried=true`, `slack_migration_map_approved=true`, Founder identity.
3. Apply controlled batches only after explicit per-batch confirmation; verify membership/rename; no agent channels.
4. Admin UI review: apps/integrations/retention/sensitive data not fully API-visible.

## Status
DRAFT ONLY. NO SLACK MUTATIONS EXECUTED.
