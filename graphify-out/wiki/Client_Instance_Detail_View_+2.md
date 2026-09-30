# Client Instance Detail View +2

> 5 nodes · cohesion 0.60

## Key Concepts

- **Admin Client Fleet** (5 connections) — `aios/dashboard/templates/admin/fleet.html`
- **Client Instance Detail View** (2 connections) — `aios/dashboard/templates/admin/client_view.html`
- **Client SSH Deploy Command Generator** (2 connections) — `aios/dashboard/templates/admin/fleet.html`
- **Register Existing Client Instance (POST /dashboard/admin/fleet/add)** (2 connections) — `aios/dashboard/templates/admin/fleet.html`
- **Instance Health Snapshot (orgs/agents counts)** (2 connections) — `aios/dashboard/templates/admin/fleet.html`

## Relationships

- [Database Restore Action (POST /dashboard/admin +2](Database_Restore_Action_POST_-dashboard-admin_+2.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/admin/client_view.html`
- `aios/dashboard/templates/admin/fleet.html`

## Audit Trail

- EXTRACTED: 6 (86%)
- INFERRED: 1 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*