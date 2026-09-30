# Billing, Budgets & Stripe Checkout

> 39 nodes · cohesion 0.08

## Key Concepts

- **billing.py** (46 connections) — `aios/api/billing.py`
- **stripe_webhook()** (10 connections) — `aios/api/billing.py`
- **create_checkout()** (8 connections) — `aios/api/billing.py`
- **create_portal()** (7 connections) — `aios/api/billing.py`
- **whatsapp_pricing.py** (6 connections) — `aios/core/whatsapp_pricing.py`
- **create_budget()** (5 connections) — `aios/api/billing.py`
- **update_budget()** (5 connections) — `aios/api/billing.py`
- **estimate_creation_cost()** (5 connections) — `aios/core/whatsapp_pricing.py`
- **BudgetCreate** (4 connections) — `aios/api/billing.py`
- **delete_budget()** (4 connections) — `aios/api/billing.py`
- **list_budgets()** (4 connections) — `aios/api/billing.py`
- **_org_hmac()** (4 connections) — `aios/api/billing.py`
- **patch_budget()** (4 connections) — `aios/api/billing.py`
- **post** (4 connections)
- **_stripe()** (4 connections) — `aios/api/billing.py`
- **usage_summary()** (4 connections) — `aios/api/billing.py`
- **CheckoutRequest** (3 connections) — `aios/api/billing.py`
- **creation_cost()** (3 connections) — `aios/api/billing.py`
- **PortalRequest** (3 connections) — `aios/api/billing.py`
- **BaseModel** (3 connections)
- **_verify_org_hmac()** (3 connections) — `aios/api/billing.py`
- **get_rates()** (3 connections) — `aios/core/whatsapp_pricing.py`
- **whatsapp_cost_for_messages()** (3 connections) — `aios/core/whatsapp_pricing.py`
- **get_plans()** (2 connections) — `aios/api/billing.py`
- **whatsapp_rates()** (2 connections) — `aios/api/billing.py`
- *... and 14 more nodes in this community*

## Relationships

- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (11 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (8 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (8 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (7 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (3 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (2 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (2 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)
- [Slack Token & Delivery](Slack_Token_&_Delivery.md) (1 shared connections)

## Source Files

- `aios/api/billing.py`
- `aios/core/whatsapp_pricing.py`

## Audit Trail

- EXTRACTED: 88 (84%)
- INFERRED: 17 (16%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*