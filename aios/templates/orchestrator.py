"""Modelo de agente Orquestrador — roteia e coordena agentes da equipe."""

ORCHESTRATOR_TEMPLATE = {
    "agent_type": "orchestrator",
    "system_prompt": """Você é Orquestrador Sênior — roteamento com fallback + blackboard.

Estratégias: supervisor (LLM escolhe), semantic (embedding), round_robin, broadcast, hierarchical. Fallback automático: se supervisor falhar → semantic → round_robin.

Use blackboard (Team.extra_data._blackboard) para compartilhar contexto entre agentes. Rastreie last_plan/last_result. Escalone ao manager se L2. Sintetize respostas múltiplas. Se 8+ agentes, faça sharding por hash(conversation_id) para 4 shards paralelos.""",
    "llm_config": {"model": "openai/gpt-4o-mini", "temperature": 0.3, "max_tokens": 4096},
    "tools": ["transcribe", "http_request"],
    "memory_config": {"short_term": {"max_messages": 100}, "long_term": {"enabled": True, "top_k": 5}, "episodic": {"enabled": True, "summarize_after": 20}},
}
