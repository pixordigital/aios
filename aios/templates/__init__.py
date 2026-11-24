"""Agent type templates — default prompts, tools, and config per agent type."""

from aios.templates.sdr import SDR_TEMPLATE
from aios.templates.lead_finder import LEAD_FINDER_TEMPLATE
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
from aios.templates.frontend import FRONTEND_TEMPLATE
from aios.templates.backend import BACKEND_TEMPLATE
from aios.templates.red import RED_TEMPLATE
from aios.templates.blue import BLUE_TEMPLATE
from aios.templates.business_teams import (
    ORCHESTRATOR_BUSINESS_TEMPLATE,
    MARKETING_TEMPLATE,
    MARKETING_MANAGER_TEMPLATE,
    CUSTOMER_SUCCESS_TEMPLATE,
    CS_MANAGER_TEMPLATE,
    REVOPS_TEMPLATE,
    REVOPS_MANAGER_TEMPLATE,
)
from aios.templates.team_managers import (
    SALES_MANAGER_TEMPLATE,
    DEV_MANAGER_TEMPLATE,
    RED_MANAGER_TEMPLATE,
    BLUE_MANAGER_TEMPLATE,
)

from aios.templates.manager_data import DATA_MANAGER_TEMPLATE
from aios.templates.media_growth import (
    MEDIA_MANAGER_TEMPLATE,
    MARKET_INTELLIGENCE_TEMPLATE,
    CONTENT_STRATEGIST_TEMPLATE,
    CONTENT_PRODUCER_TEMPLATE,
)

_SCAFFOLD_MARKER = "# Camada 1 — Papel e escopo"
_PROMPT_SCAFFOLD = """

# Camada 1 — Papel e escopo
Faça apenas o que seu papel define. FORA DO ESCOPO: prometer números, prazos ou capacidades não verificados no código.

# Camada 2 — Regras duras
Nunca invente dado. Nunca prometa limite que não existe em `PLANS`/`check_org_limits`. Ações irreversíveis exigem aprovação humana.

# Camada 3 — Procedimento
Consulte dado real antes de responder. Se precisar de ferramenta, chame-a antes de afirmar.

# Camada 4 — Comportamento na dúvida
Na dúvida, diga "não sei" e aponte o que falta verificar. Exemplo de erro corrigido — pergunta: "quantos minutos de voz?"; errado: "10k minutos"; correto: "não sei: `voice_minutes` não existe em `PLANS`; verifico antes de prometer".
"""

TEMPLATES = {
    "orchestrator": ORCHESTRATOR_TEMPLATE,
    "manager": MANAGER_TEMPLATE,
    "manager_sales": SALES_MANAGER_TEMPLATE,
    "manager_dev": DEV_MANAGER_TEMPLATE,
    "manager_red": RED_MANAGER_TEMPLATE,
    "manager_blue": BLUE_MANAGER_TEMPLATE,
    "manager_data": DATA_MANAGER_TEMPLATE,
    "media_manager": MEDIA_MANAGER_TEMPLATE,
    "market_intelligence": MARKET_INTELLIGENCE_TEMPLATE,
    "content_strategist": CONTENT_STRATEGIST_TEMPLATE,
    "content_producer": CONTENT_PRODUCER_TEMPLATE,
    # Cross-team coordination and the three functions a business runs without
    # that Sales, Support, Data and Dev do not cover.
    "orchestrator_business": ORCHESTRATOR_BUSINESS_TEMPLATE,
    "manager_marketing": MARKETING_MANAGER_TEMPLATE,
    "marketing": MARKETING_TEMPLATE,
    "manager_cs": CS_MANAGER_TEMPLATE,
    "customer_success": CUSTOMER_SUCCESS_TEMPLATE,
    "manager_revops": REVOPS_MANAGER_TEMPLATE,
    "revops": REVOPS_TEMPLATE,
    "sdr": SDR_TEMPLATE,
    "lead_finder": LEAD_FINDER_TEMPLATE,
    "closer": CLOSER_TEMPLATE,
    "support": SUPPORT_TEMPLATE,
    "data_analyst": DATA_ANALYST_TEMPLATE,
    "data_scientist": DATA_SCIENTIST_TEMPLATE,
    "deal_auditor": DEAL_AUDITOR_TEMPLATE,
    "pricing_guardian": PRICING_GUARDIAN_TEMPLATE,
    "evidence_compiler": EVIDENCE_COMPILER_TEMPLATE,
    "performance_watcher": PERFORMANCE_WATCHER_TEMPLATE,
    "human_auditor": HUMAN_AUDITOR_TEMPLATE,
    "frontend": FRONTEND_TEMPLATE,
    "backend": BACKEND_TEMPLATE,
    "red": RED_TEMPLATE,
    "blue": BLUE_TEMPLATE,
}


def apply_template(agent_type: str, overrides: dict | None = None) -> dict:
    template = TEMPLATES.get(agent_type)
    if not template:
        raise ValueError(f"Unknown agent type: {agent_type}")
    config = dict(template)
    if overrides:
        config.update(overrides)
    prompt = config.get("system_prompt") or ""
    if _SCAFFOLD_MARKER not in prompt:
        config["system_prompt"] = prompt.rstrip() + _PROMPT_SCAFFOLD
    return config
