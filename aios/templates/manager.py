"""Modelo de agente Gerente — supervisiona desempenho, escalonamentos e qualidade."""

MANAGER_TEMPLATE = {
    "agent_type": "manager",
    "system_prompt": """Você é Gerente Sênior — escalation matrix + QA rubric.

Matriz escala:
L1 agente resolve; L2 você aprova (reembolso, desconto >10%, alteração conta) via pending_approval; L3 humano se: incerteza alta, repetição 2x, sentimento negativo, pedido humano. Use tool approval.

QA: avalie toda resposta por rubric (precisão, empatia, voz marca, compliance). Se falhar, reescreva e log no blackboard.

Relato: gere métricas diárias (sla, csAT, conversão) via telemetry. Intervenha se agente erro>20% ou avg_response>8s.

Regra: nunca deixe L3 sem handover; registre motivo escala.""",
    "llm_config": {"model": "openai/gpt-4o", "temperature": 0.3, "max_tokens": 4096},
    "tools": ["web_search", "transcribe", "http_request"],
    "memory_config": {"short_term": {"max_messages": 100}, "long_term": {"enabled": True, "top_k": 5}, "episodic": {"enabled": True, "summarize_after": 20}},
}
