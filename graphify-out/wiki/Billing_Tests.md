# Billing Tests

> 16 nodes · cohesion 0.17

## Key Concepts

- **TestBilling** (8 connections) — `tests/test_billing.py`
- **AsyncClient** (6 connections)
- **test_billing.py** (3 connections) — `tests/test_billing.py`
- **.test_create_checkout()** (3 connections) — `tests/test_billing.py`
- **.test_create_checkout_requires_auth()** (3 connections) — `tests/test_billing.py`
- **.test_create_portal()** (3 connections) — `tests/test_billing.py`
- **.test_create_portal_requires_auth()** (3 connections) — `tests/test_billing.py`
- **.test_get_plans()** (3 connections) — `tests/test_billing.py`
- **.test_usage_summary()** (3 connections) — `tests/test_billing.py`
- **Test creating Stripe checkout session.** (1 connections) — `tests/test_billing.py`
- **Test creating Stripe customer portal session.** (1 connections) — `tests/test_billing.py`
- **Test getting available plans.** (1 connections) — `tests/test_billing.py`
- **Test getting usage summary for org.** (1 connections) — `tests/test_billing.py`
- **Unauthenticated checkout creation must be rejected.** (1 connections) — `tests/test_billing.py`
- **Unauthenticated portal creation must be rejected.** (1 connections) — `tests/test_billing.py`
- **Billing and Stripe integration tests.** (1 connections) — `tests/test_billing.py`

## Relationships

- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)

## Source Files

- `tests/test_billing.py`

## Audit Trail

- EXTRACTED: 22 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*