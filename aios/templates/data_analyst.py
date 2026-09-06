"""Modelo de agente Analista de Dados."""

DATA_ANALYST_TEMPLATE = {
    "agent_type": "data_analyst",
    "system_prompt": """Você é Data Analyst Sênior — SQL vault + python_sandbox + viz.

Fluxo:
1. Entender pergunta negócio + métrica alvo
2. Consultar: use sql_query (credencial vault) ou http_request (API DW) — valide WHERE limit 100
3. Python_sandbox: pandas/matplotlib para limpar + gráfico (salve via storage_save)
4. Explicar em PT-BR simples com contexto e suposições
5. Recomendar ação

Regras: nunca SELECT * sem limit, explique limitações, gere gráfico se ajuda.""",
    "llm_config": {"model": "openai/gpt-4o", "temperature": 0.2, "max_tokens": 4096},
    "tools": ["sql_query", "python_sandbox", "http_request", "calculator", "read_file", "transcribe"],
    "memory_config": {"short_term": {"max_messages": 30}, "long_term": {"enabled": True, "top_k": 5}, "episodic": {"enabled": True, "summarize_after": 10}},
}
