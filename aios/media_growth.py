import re

from aios.templates import apply_template

PHASE1_ROLES = (
    "Media Manager",
    "Market Intelligence Researcher",
    "Content Strategist",
    "Content Producer",
)

ROLE_SPECS: dict[str, dict] = {
    "Media Manager": {
        **apply_template("media_manager"),
        "governance_config": {
            "autonomy": "draft",
            "autonomous": False,
            "max_trials": 3,
            "hitl_enabled": True,
            "hitl_value_threshold": 5000,
            "hitl_discount_threshold": 10,
            "max_tokens_per_run": 500000,
            "allowed_tools": "__all__",
            "denied_tools": [],
            "max_iterations": 10,
            "hard_rules": [
                "no_strategy_change",
                "no_process_redefinition",
                "no_spend_authorization",
                "no_personal_publishing",
            ],
        },
    },
    "Market Intelligence Researcher": {
        **apply_template("market_intelligence"),
        "governance_config": {
            "autonomy": "draft",
            "autonomous": False,
            "max_trials": 3,
            "hitl_enabled": True,
            "hitl_value_threshold": 5000,
            "hitl_discount_threshold": 10,
            "max_tokens_per_run": 500000,
            "allowed_tools": "__all__",
            "denied_tools": [],
            "max_iterations": 10,
            "hard_rules": [
                "traceable_material_claims",
                "label_fact_estimate_interpretation_hypothesis",
                "no_hypothesis_as_fact",
                "public_sources_only",
            ],
        },
    },
    "Content Strategist": {
        **apply_template("content_strategist"),
        "governance_config": {
            "autonomy": "draft",
            "autonomous": False,
            "max_trials": 3,
            "hitl_enabled": True,
            "hitl_value_threshold": 5000,
            "hitl_discount_threshold": 10,
            "max_tokens_per_run": 500000,
            "allowed_tools": "__all__",
            "denied_tools": [],
            "max_iterations": 10,
            "hard_rules": ["exact_brief_fields", "no_positioning_change", "no_invented_evidence"],
        },
    },
    "Content Producer": {
        **apply_template("content_producer"),
        "governance_config": {
            "autonomy": "draft",
            "autonomous": False,
            "max_trials": 3,
            "hitl_enabled": True,
            "hitl_value_threshold": 5000,
            "hitl_discount_threshold": 10,
            "max_tokens_per_run": 500000,
            "allowed_tools": "__all__",
            "denied_tools": [],
            "max_iterations": 10,
            "hard_rules": [
                "no_invented_personal_experience",
                "no_invented_customer_cases",
                "no_invented_performance_numbers",
                "no_invented_credentials",
                "human_approval_before_publish",
            ],
        },
    },
    "Quality & Risk Reviewer": {
        "agent_type": "custom",
        "system_prompt": (
            "Você verifica fatos e riscos e pode bloquear conteúdo, mas nunca publica. Sinais "
            "especiais LATAM Cargo: operações confidenciais, dados de clientes ou funcionários, "
            "métricas internas, endosso do empregador e conflito com política de emprego."
        ),
        "tools": ["rag_search", "knowledge_search", "current_datetime"],
        "llm_config": {"model": "openai/gpt-4o", "temperature": 0.1, "max_tokens": 4096},
        "memory_config": {
            "short_term": {"max_messages": 100},
            "long_term": {"enabled": True, "top_k": 6},
            "episodic": {"enabled": True, "summarize_after": 15},
        },
        "governance_config": {
            "autonomy": "draft",
            "autonomous": False,
            "max_trials": 3,
            "hitl_enabled": True,
            "hitl_value_threshold": 5000,
            "hitl_discount_threshold": 10,
            "max_tokens_per_run": 500000,
            "allowed_tools": "__all__",
            "denied_tools": [],
            "max_iterations": 10,
            "can_block": True,
            "can_publish": False,
            "hard_rules": [
                "no_confidential_ops",
                "no_customer_or_employee_info",
                "no_internal_metrics",
                "no_employer_endorsement",
                "no_employment_policy_conflict",
            ],
        },
    },
    "Distribution & Community Manager": {
        "agent_type": "custom",
        "system_prompt": (
            "Você prepara, agenda e monitora distribuição e comunidade, sem publicar sem "
            "aprovação explícita. Restrições: sem impersonação, sem DMs ou conexões não "
            "solicitadas, sem publicação sem aprovação humana explícita."
        ),
        "tools": ["calendar_create_event", "send_email", "current_datetime", "rag_search"],
        "llm_config": {"model": "openai/gpt-4o", "temperature": 0.2, "max_tokens": 4096},
        "memory_config": {
            "short_term": {"max_messages": 100},
            "long_term": {"enabled": True, "top_k": 6},
            "episodic": {"enabled": True, "summarize_after": 15},
        },
        "governance_config": {
            "autonomy": "draft",
            "autonomous": False,
            "max_trials": 3,
            "hitl_enabled": True,
            "hitl_value_threshold": 5000,
            "hitl_discount_threshold": 10,
            "max_tokens_per_run": 500000,
            "allowed_tools": "__all__",
            "denied_tools": [],
            "max_iterations": 10,
            "can_publish": False,
            "hard_rules": [
                "no_impersonation",
                "no_unsolicited_dms",
                "no_unsolicited_connections",
                "no_publish_without_explicit_approval",
            ],
        },
    },
    "Growth & Performance Analyst": {
        "agent_type": "custom",
        "system_prompt": (
            "Você analisa impressões→engajamento→conversas de negócio→oportunidades "
            "qualificadas, não impressões isoladas. Recomende ações pela qualidade das "
            "conversas e oportunidades, com custo por post aprovado e receita quando houver."
        ),
        "tools": ["sql_query", "crm_pipeline_stats", "calculator", "current_datetime", "rag_search"],
        "llm_config": {"model": "openai/gpt-4o", "temperature": 0.2, "max_tokens": 4096},
        "memory_config": {
            "short_term": {"max_messages": 100},
            "long_term": {"enabled": True, "top_k": 6},
            "episodic": {"enabled": True, "summarize_after": 15},
        },
        "governance_config": {
            "autonomy": "draft",
            "autonomous": False,
            "max_trials": 3,
            "hitl_enabled": True,
            "hitl_value_threshold": 5000,
            "hitl_discount_threshold": 10,
            "max_tokens_per_run": 500000,
            "allowed_tools": "__all__",
            "denied_tools": [],
            "max_iterations": 10,
            "hard_rules": ["no_impressions_only_optimization", "qualified_conversations_first"],
        },
    },
}

_BRIEF_FIELDS = (
    "Topic",
    "Audience",
    "Problem",
    "Objective",
    "Angle",
    "Evidence",
    "Format",
    "CTA",
    "Success metric",
)

_NUMERIC_CLAIM_RE = re.compile(
    r"(?:R\$\s*)?\d+(?:[.,]\d+)*(?:\s*%|\s*(?:mil|k|m|bi|reais))?", re.IGNORECASE
)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_FORBIDDEN_PATTERNS = (
    ("invented_experience", r"na minha experiência|minha experiência|eu vivi|eu liderei|eu implementei|eu participei|eu gerenciei|eu fiz|eu fui|in my experience|i led|i implemented"),
    ("invented_case", r"caso de sucesso|estudo de caso|nosso cliente|um cliente|cliente específico|case study|our customer"),
    ("invented_credential", r"credencial|certificado|formado em|pós-graduado|phd|mba|credential|certified"),
)
_CONFIDENTIAL_PATTERNS = (
    ("confidential_ops_terms", r"confidencial|sigiloso|operação interna|informação interna"),
    ("customer_or_employee_info_terms", r"dados de clientes|informações de clientes|funcionário|colaborador|employee|customer data"),
    ("internal_metrics_terms", r"métrica interna|número interno|kpi interno|internal metric"),
    ("employer_endorsement_terms", r"endosso do empregador|empregador endossa|endosso da empresa|apoiado pela latam|latam cargo endossa|employer endorsement"),
    ("employment_policy_conflict_terms", r"política de emprego|contrato de trabalho|recrutamento|contratação|rh|employment policy"),
)


def agent_config(role_name: str) -> dict:
    if role_name not in ROLE_SPECS:
        raise KeyError(role_name)
    return {"name": role_name, **ROLE_SPECS[role_name], "status": "draft"}


def build_editorial_brief(
    research_brief: dict, *, audience: str, objective: str, cta: str
) -> dict:
    return {
        "Topic": research_brief.get("topic", ""),
        "Audience": audience,
        "Problem": research_brief.get("problem", ""),
        "Objective": objective,
        "Angle": research_brief.get("angle", ""),
        "Evidence": research_brief.get("evidence", []),
        "Format": research_brief.get("format", ""),
        "CTA": cta,
        "Success metric": research_brief.get("success_metric", ""),
    }


def review_content(
    draft: str, evidence: list[dict], *, approved_examples: list[str] | None = None
) -> dict:
    # shortcut: lexical checks only; no claim is fact-verified here.
    issues: list[str] = []
    high = False
    medium = False

    claims = [m.group(0).strip() for m in _NUMERIC_CLAIM_RE.finditer(draft or "")]
    evidence_text = " ".join(
        str(value)
        for item in (evidence or [])
        for value in (item.values() if isinstance(item, dict) else [item])
        if value is not None
    ).casefold()
    unsupported = []
    for claim in claims:
        core = _NUMBER_RE.search(claim)
        core_text = core.group(0) if core else claim
        if claim.casefold() in evidence_text or core_text in evidence_text:
            continue
        unsupported.append(claim)
    if unsupported:
        high = True
        issues.extend(f"numeric_claim_without_evidence:{claim}" for claim in unsupported)

    text = (draft or "").casefold()
    for issue, pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            high = True
            issues.append(issue)
    for issue, pattern in _CONFIDENTIAL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            high = True
            issues.append(issue)

    if not any(str(example).strip() for example in (approved_examples or [])):
        medium = True
        issues.append("missing_approved_voice_examples")

    coverage = round((len(claims) - len(unsupported)) / len(claims), 4) if claims else 1.0
    risk = "high" if high else "medium" if medium or issues else "low"
    return {
        "ok": not issues,
        "issues": issues,
        "risk": risk,
        "evidence_coverage": coverage,
    }


def prepare_distribution(content: str, approval: dict) -> dict:
    if not approval.get("approved_by") or not approval.get("approved_at"):
        return {"ok": False, "error": "missing_human_approval"}
    return {
        "ok": True,
        "status": "ready_for_manual_publish",
        "content": content,
        "approved_by": approval.get("approved_by"),
        "approved_at": approval.get("approved_at"),
        "external_side_effects": [],
    }


def analyze_performance(rows: list[dict]) -> dict:
    totals = {
        "impressions": 0,
        "engagements": 0,
        "profile_views": 0,
        "qualified_conversations": 0,
        "cost": 0,
        "revenue": 0,
    }
    for row in rows:
        for key in totals:
            value = row.get(key, 0)
            totals[key] += value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

    impressions = totals["impressions"]
    engagements = totals["engagements"]
    qualified = totals["qualified_conversations"]
    engagement_rate = engagements / impressions if impressions else 0.0
    cost_per_approved_post = totals["cost"] / len(rows) if rows else 0.0
    qualified_conversation_rate = qualified / engagements if engagements else 0.0

    if qualified:
        recommendation = "prioritize_content_that_generates_qualified_conversations"
    elif engagements:
        recommendation = "convert_engagement_into_qualified_conversations"
    else:
        recommendation = "do_not_optimize_for_impressions_alone_use_qualified_conversations"

    return {
        **totals,
        "engagement_rate": engagement_rate,
        "cost_per_approved_post": cost_per_approved_post,
        "qualified_conversation_rate": qualified_conversation_rate,
        "recommendation": recommendation,
    }


def _self_check() -> None:
    assert len(ROLE_SPECS) == 7
    assert len(PHASE1_ROLES) == 4
    assert [agent_config(role)["agent_type"] for role in PHASE1_ROLES] == [
        "media_manager",
        "market_intelligence",
        "content_strategist",
        "content_producer",
    ]
    for role in PHASE1_ROLES:
        prompt = agent_config(role)["system_prompt"]
        assert "# Camada 1" in prompt
        assert len(prompt) > 400
    for role in ROLE_SPECS:
        config = agent_config(role)
        assert config["status"] == "draft"
        for key in ("agent_type", "system_prompt", "tools", "llm_config", "memory_config", "governance_config"):
            assert key in config
    try:
        agent_config("Unknown Role")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown role must raise KeyError")

    evidence = [{"source": "public", "claim": "P"}]
    brief = build_editorial_brief(
        {
            "topic": "T",
            "problem": "P",
            "angle": "A",
            "format": "post",
            "success_metric": "qualified leads",
            "evidence": evidence,
        },
        audience="Ops",
        objective="Leads",
        cta="Comente",
    )
    assert set(brief) == set(_BRIEF_FIELDS)
    assert brief["Evidence"] == evidence
    assert build_editorial_brief({}, audience="A", objective="O", cta="C")["Evidence"] == []

    bad = review_content(
        "Na minha experiência crescemos 30% com dados internos.",
        [],
        approved_examples=None,
    )
    assert bad["ok"] is False
    assert bad["risk"] == "high"
    assert bad["evidence_coverage"] < 1.0
    assert "missing_approved_voice_examples" in bad["issues"]

    good = review_content("Resumo sem números.", [], approved_examples=["Tom direto."])
    assert good == {"ok": True, "issues": [], "risk": "low", "evidence_coverage": 1.0}

    assert prepare_distribution("x", {}) == {"ok": False, "error": "missing_human_approval"}
    artifact = prepare_distribution("x", {"approved_by": "ana", "approved_at": "2026-01-01"})
    assert artifact["status"] == "ready_for_manual_publish"
    assert artifact["external_side_effects"] == []

    empty = analyze_performance([])
    assert empty["impressions"] == 0
    assert empty["engagement_rate"] == 0.0
    assert empty["cost_per_approved_post"] == 0.0
    assert "qualified" in empty["recommendation"]

    stats = analyze_performance(
        [
            {
                "impressions": 100,
                "engagements": 10,
                "profile_views": 4,
                "qualified_conversations": 2,
                "cost": 20,
                "revenue": 50,
            },
            {"impressions": 100, "engagements": 0, "qualified_conversations": 0, "cost": 20},
        ]
    )
    assert stats["impressions"] == 200
    assert stats["engagements"] == 10
    assert stats["engagement_rate"] == 0.05
    assert stats["cost_per_approved_post"] == 20
    assert stats["qualified_conversation_rate"] == 0.2
    assert "qualified" in stats["recommendation"]


if __name__ == "__main__":
    _self_check()
