# Database Restore Action (POST /dashboard/admin +2

> 9 nodes · cohesion 0.25

## Key Concepts

- **Dead Letter Queue Console** (5 connections) — `aios/dashboard/templates/admin/dlq.html`
- **Admin Backup & Restore** (4 connections) — `aios/dashboard/templates/admin/backup.html`
- **Admin Sub-navigation Tab Bar** (4 connections) — `aios/dashboard/templates/admin/orgs.html`
- **Database Restore Action (POST /dashboard/admin/backup/restore)** (2 connections) — `aios/dashboard/templates/admin/backup.html`
- **S3 Backup Sync & Bucket Versioning** (2 connections) — `aios/dashboard/templates/admin/backup.html`
- **DLQ Organization Filter** (2 connections) — `aios/dashboard/templates/admin/dlq.html`
- **DLQ Requeue Action** (2 connections) — `aios/dashboard/templates/admin/dlq.html`
- **Trigger Manual Backup (POST /dashboard/admin/backup)** (1 connections) — `aios/dashboard/templates/admin/backup.html`
- **DLQ Entry Delete Action** (1 connections) — `aios/dashboard/templates/admin/dlq.html`

## Relationships

- [Admin & Custom Domain Config](Admin_&_Custom_Domain_Config.md) (2 shared connections)
- [Agent Version History](Agent_Version_History.md) (1 shared connections)
- [Workflow DAG Builder UI](Workflow_DAG_Builder_UI.md) (1 shared connections)
- [Client Instance Detail View +2](Client_Instance_Detail_View_+2.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/admin/backup.html`
- `aios/dashboard/templates/admin/dlq.html`
- `aios/dashboard/templates/admin/orgs.html`

## Audit Trail

- EXTRACTED: 10 (71%)
- INFERRED: 4 (29%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*