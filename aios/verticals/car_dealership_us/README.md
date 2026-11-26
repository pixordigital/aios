# US Car Dealership vertical (AIOS)

Focus: governed inbound lead capture + bounded follow-up for a **US car dealership** (sales). Not a DMS; works alongside CRM/DMS.

## What this vertical provides

- **Profile** (`CarDealershipUSProfile`): approved facts only (business name, services/offerings, hours, escalation rules). Agent must not invent pricing/hours/policies.
- **Paid workflow contracts (ICM-X)**:
  - `car_dealership_us_lead_capture` — qualify inquiry → qualified lead or human handoff
  - `car_dealership_us_lead_follow_up` — bounded follow-up (approval required); respects opt-out, cadence, cap
- **Policies** (pure): opt-out detection, follow-up cadence/cap, escalation keyword → destination
- **Metrics**: outcome counts + rates (attribution reported with source/confidence; not revenue truth)

## Example profile (store in agent/org `extra_data` or your config)

```json
{
  "business_name": "Example Motors (US)",
  "services": [
    {"name": "New vehicle sales", "notes": "Quote from approved inventory/pricing system"},
    {"name": "Used vehicle sales"},
    {"name": "Trade-in appraisal", "notes": "Schedule in-person appraisal"}
  ],
  "hours": {
    "mon": "09:00-19:00",
    "tue": "09:00-19:00",
    "wed": "09:00-19:00",
    "thu": "09:00-19:00",
    "fri": "09:00-19:00",
    "sat": "10:00-18:00",
    "sun": "closed"
  },
  "escalation_rules": {
    "lawyer": "general_manager",
    "attorney": "general_manager",
    "lemon law": "general_manager",
    "warranty dispute": "service_manager",
    "financing complaint": "finance_manager"
  },
  "max_follow_ups": 2,
  "min_hours_between_follow_ups": 24
}
```

## Smallest rollout (recommended)

1. One store, one inbound channel (e.g. WhatsApp/web chat), one BDC/sales team.
2. Load approved facts only; set escalation destinations.
3. Enable `car_dealership_us_lead_capture` + `car_dealership_us_lead_follow_up`.
4. Review weekly: approvals, outcomes (`/api/analytics/outcomes`), cost, dropped chats.
5. Expand after measured value > cost (service reminders, trade-in flows later).

## Agent `extra_data` (example)

For a paid governed agent (ICM-X bound). Store under the agent’s `extra_data` (and keep profile facts in the same place or your config layer as you prefer):

```json
{
  "workflow_class": "car_dealership_us_lead_capture",
  "workflow_registry": "aios.verticals.car_dealership_us.workflows",
  "icm": {
    "workspace_id": "cd_us_ops",
    "stage_id": "car_dealership_us_lead_capture"
  }
}
```

For follow-up agent use `workflow_class": "car_dealership_us_lead_follow_up"` and matching `stage_id`. `workflow_registry` is optional if using the default fallback, but explicit is clearer.

## Risks / notes

- Opt-out phrases included (EN + common ES); **TCPA quiet hours / consent storage** are not enforced here — add at channel/compliance layer.
- Analytics returns `attributed_value` (USD) plus legacy `attributed_value_brl` alias and `currency="USD"`. Treat as configured currency amount in reports.
- Do not promise financing/price guarantees the profile does not state.
