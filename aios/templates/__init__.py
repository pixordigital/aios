"""Agent type templates — default prompts, tools, and config per agent type."""

from aios.templates.sdr import SDR_TEMPLATE
from aios.templates.closer import CLOSER_TEMPLATE
from aios.templates.support import SUPPORT_TEMPLATE
from aios.templates.data_analyst import DATA_ANALYST_TEMPLATE
from aios.templates.data_scientist import DATA_SCIENTIST_TEMPLATE
from aios.templates.orchestrator import ORCHESTRATOR_TEMPLATE
from aios.templates.manager import MANAGER_TEMPLATE
from aios.templates.deal_auditor import DEAL_AUDITOR_TEMPLATE
from aios.templates.pricing_guardian import PRICING_GUARDIAN_TEMPLATE
from aios.templates.evidence_compiler import EVIDENCE_COMPILER_TEMPLATE
from aios.templates.performance_watcher import PERFORMANCE_WATCHER_TEMPLATE
from aios.templates.human_auditor import HUMAN_AUDITOR_TEMPLATE

TEMPLATES = {
    "orchestrator": ORCHESTRATOR_TEMPLATE,
    "manager": MANAGER_TEMPLATE,
    "sdr": SDR_TEMPLATE,
    "closer": CLOSER_TEMPLATE,
    "support": SUPPORT_TEMPLATE,
    "data_analyst": DATA_ANALYST_TEMPLATE,
    "data_scientist": DATA_SCIENTIST_TEMPLATE,
    "deal_auditor": DEAL_AUDITOR_TEMPLATE,
    "pricing_guardian": PRICING_GUARDIAN_TEMPLATE,
    "evidence_compiler": EVIDENCE_COMPILER_TEMPLATE,
    "performance_watcher": PERFORMANCE_WATCHER_TEMPLATE,
    "human_auditor": HUMAN_AUDITOR_TEMPLATE,
}


def apply_template(agent_type: str, overrides: dict | None = None) -> dict:
    template = TEMPLATES.get(agent_type)
    if not template:
        raise ValueError(f"Unknown agent type: {agent_type}")
    config = dict(template)
    if overrides:
        config.update(overrides)
    return config
