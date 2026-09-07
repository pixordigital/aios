"""Solution packs — modo lojista: 1 objetivo = agente + prompt + canal prontos."""

SOLUTIONS = {
    "vender": {
        "key": "vender",
        "title": "Vender — SDR outbound",
        "desc": "Prospecção ativa: aborda leads, qualifica e agenda. Liga + WhatsApp.",
        "agent_type": "sdr",
        "agent_name": "SDR Vendedor",
        "tools": ["voice_call", "lead_score", "crm"],
        "channel": "voice",
        "addon": (
            "Você é o SDR da empresa. Missão: contatar cada lead em até 5 minutos, "
            "qualificar (nome, interesse, orçamento, prazo) e agendar reunião ou fechar venda simples. "
            "Seja direto, humano, PT-BR. Nunca invente preço ou prazo. Sem resposta após 2 tentativas, registre e parta pro próximo."
        ),
    },
    "atender": {
        "key": "atender",
        "title": "Atender — Suporte WhatsApp",
        "desc": "Responde clientes 24/7: dúvidas, status pedido, troca. Humano assume se travar.",
        "agent_type": "support",
        "agent_name": "Atendente",
        "tools": ["transcribe", "crm"],
        "channel": "evolution",
        "addon": (
            "Você é o atendente da empresa. Missão: resolver dúvidas rápido (produto, preço, prazo, status, troca). "
            "Resposta curta, PT-BR, 1 pergunta por vez. Se não souber ou cliente irritado, transfira pra humano com resumo."
        ),
    },
    "recuperar": {
        "key": "recuperar",
        "title": "Recuperar — Carrinho abandonado",
        "desc": "Chama quem desistiu: 1h, 24h e 72h depois. Oferta, não desconto automático.",
        "agent_type": "sdr",
        "agent_name": "Recuperador",
        "tools": ["voice_call", "crm"],
        "channel": "voice",
        "addon": (
            "Você recupera vendas perdidas. Missão: contatar em 1h / 24h / 72h após abandono, "
            "entender objeção (preço, dúvida, prazo), oferecer ajuda e fechar. Desconto só se objeção for preço e valor permitir. "
            "Registre motivo da perda em cada contato."
        ),
    },
}


def get_solution(key: str) -> dict:
    sol = SOLUTIONS.get(key)
    if not sol:
        raise ValueError(f"Unknown solution: {key}")
    return dict(sol)
