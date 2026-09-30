# Admin & Custom Domain Config

> 16 nodes · cohesion 0.16

## Key Concepts

- **AIOS Dashboard Shell (base.html)** (7 connections) — `aios/dashboard/templates/base.html`
- **Admin Organization Detail** (4 connections) — `aios/dashboard/templates/admin/org_detail.html`
- **Admin Organizations List** (4 connections) — `aios/dashboard/templates/admin/orgs.html`
- **Superadmin Org Switcher** (4 connections) — `aios/dashboard/templates/base.html`
- **Sidebar Navigation** (4 connections) — `aios/dashboard/templates/base.html`
- **White-Label Branding Toggle (org_white_label)** (4 connections) — `aios/dashboard/templates/base.html`
- **Custom Domain Configuration** (2 connections) — `aios/dashboard/templates/admin/org_detail.html`
- **Org Suspend / Unsuspend Action** (2 connections) — `aios/dashboard/templates/admin/org_detail.html`
- **Org White-Label Toggle** (2 connections) — `aios/dashboard/templates/admin/org_detail.html`
- **Impersonation Mode Indicator** (2 connections) — `aios/dashboard/templates/base.html`
- **Plan Label Rendering** (1 connections) — `aios/dashboard/templates/admin/orgs.html`
- **Admin Nav Visibility Gate (is_superadmin)** (1 connections) — `aios/dashboard/templates/base.html`
- **Mobile Bottom Navigation** (1 connections) — `aios/dashboard/templates/base.html`
- **Dark Theme Design Token System** (1 connections) — `aios/dashboard/templates/base.html`
- **Quick Agent Modal Include** (1 connections) — `aios/dashboard/templates/base.html`
- **Sidebar Collapse Persistence (localStorage + Ctrl+B)** (1 connections) — `aios/dashboard/templates/base.html`

## Relationships

- [Database Restore Action (POST /dashboard/admin +2](Database_Restore_Action_POST_-dashboard-admin_+2.md) (2 shared connections)
- [Billing & Budget Dashboard](Billing_&_Budget_Dashboard.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/admin/org_detail.html`
- `aios/dashboard/templates/admin/orgs.html`
- `aios/dashboard/templates/base.html`

## Audit Trail

- EXTRACTED: 19 (86%)
- INFERRED: 3 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*