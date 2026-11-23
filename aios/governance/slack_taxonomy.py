"""Slack workspace taxonomy as data, not as a second source of truth.

Slack coordinates. AIOS remains the system of record for tasks, approvals,
customers, knowledge, KPIs and process execution. Channel creation stays blocked
until the real workspace is inventoried and the migration map is approved.
"""

from __future__ import annotations

PROPOSED_CHANNELS: dict[str, tuple[str, ...]] = {
    "leadership": (
        "company-announcements",
        "founder-office",
        "leadership",
        "company-decisions",
        "company-performance",
    ),
    "departments": (
        "dept-sales",
        "dept-lia",
        "dept-media-growth",
        "dept-data",
        "dept-product",
        "dept-engineering",
        "dept-operations",
        "dept-finance",
    ),
    "cross_functional": (
        "collab-sales-lia",
        "collab-sales-data",
        "collab-media-data",
        "collab-product-engineering",
        "collab-privacy-security",
        "collab-revenue-operations",
    ),
    "organizational_systems": (
        "org-process-improvement",
        "org-skills",
        "org-experiments",
        "org-innovation-learning",
        "org-kpi-analytics",
        "org-random-legacy",
    ),
    "restricted_governance": (
        "security-incidents",
        "security-monitoring",
        "privacy-governance",
        "privacy-incidents",
    ),
    "projects": (
        "project-showcar-pilot",
        "project-aios-product",
        "project-lia-launch",
    ),
}

SYSTEM_OF_RECORD = {
    "discussions": "slack",
    "tasks": "aios_ocp",
    "approvals": "aios_decision_approval",
    "customer_information": "aios_crm",
    "documents": "aios_knowledge",
    "kpis": "aios_organizational_intelligence",
    "process_execution": "aios_process_workflow_engines",
    "skills": "aios_skills",
}

RESTRICTED_AREAS = ("restricted_governance",)

# Never acceptable in a channel message.
FORBIDDEN_CONTENT = ("credentials", "unrestricted_personal_data", "investigation_evidence")


class TaxonomyError(ValueError):
    """Channel name or area violates the convention."""


def validate_channel(area: str, name: str) -> str:
    """Names must be prefixed by their area and must never create an agent channel."""
    if area not in PROPOSED_CHANNELS:
        raise TaxonomyError(f"unknown area: {area}")
    if name not in PROPOSED_CHANNELS[area]:
        raise TaxonomyError(f"channel {name} not in proposed taxonomy for {area}")
    prefixes = {
        "leadership": ("company-", "founder-", "leadership"),
        "departments": ("dept-",),
        "cross_functional": ("collab-",),
        "organizational_systems": ("org-",),
        "restricted_governance": ("security-", "privacy-"),
        "projects": ("project-",),
    }
    allowed = prefixes[area]
    if not any(name == p or name.startswith(p) for p in allowed):
        raise TaxonomyError(f"channel {name} lacks the {area} prefix")
    if name.startswith("agent-"):
        raise TaxonomyError("do not create a channel per agent")
    return name


def slack_may_become_decision() -> bool:
    return False


def migration_steps() -> tuple[str, ...]:
    return (
        "inspect real workspace (channels, members, privacy, integrations, usage)",
        "map existing channels to taxonomy",
        "identify duplicates, obsolete channels and sensitive data",
        "prepare keep/rename/merge/archive/create migration map",
        "obtain founder approval before structural changes",
        "apply in controlled batches and verify membership",
        "publish conventions and system-of-record rules",
    )
