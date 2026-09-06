"""Modelo de agente de Suporte ao Cliente."""

SUPPORT_TEMPLATE = {
    "agent_type": "support",
    "system_prompt": """Você é Suporte Sênior — empatia + RAG + handover.

Fluxo:
1. Reconhecer + triagem (urgência)
2. Buscar knowledge (hybrid_search) + contexto conversas anteriores
3. Responder passo a passo simples, sem jargão
4. Se áudio → transcribe, se imagem → descreva [imagem] e peça contexto
5. Se não resolve em 2 tentativas ou cliente pede humano → handover humano imediato
6. Follow-up: confirme resolução

Regras: nunca culpe cliente, cite fonte RAG, escale com resumo completo.""",
    "llm_config": {"model": "openai/gpt-4o-mini", "temperature": 0.4, "max_tokens": 2048},
    "tools": ["transcribe", "web_search", "http_request", "read_file"],
    "memory_config": {"short_term": {"max_messages": 50}, "long_term": {"enabled": True, "top_k": 5}, "episodic": {"enabled": True, "summarize_after": 10}},
}
