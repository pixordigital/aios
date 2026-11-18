"""Compilador Plug-and-Play para o AIOS (Modo Simples).

Converte intenções de negócio, soluções pré-formatadas e escolhas descomplicadas
em System Prompts blindados, seleção de modelos e configurações completas de Agent.
"""

from typing import Any, Dict, List, Optional

PLUG_AND_PLAY_SOLUTIONS: Dict[str, Dict[str, Any]] = {
    "whatsapp_atendente": {
        "title": "Atendente WhatsApp & Loja",
        "badge": "Varejo & Serviços",
        "desc": "Responde 24/7 sobre catálogo, produtos, horários, localização e pedidos.",
        "icon": "🛍️",
        "agent_type": "support",
        "tools": ["transcribe", "retrieval", "crm_list_deals", "crm_update_deal"],
        "base_prompt": (
            "Você é o atendente virtual oficial da empresa {business_name}.\n"
            "Atividade da empresa: {business_description}\n"
            "Tom de conversa: {tone_text}\n"
            "Horário Comercial: {business_hours_text}\n\n"
            "MISSÃO:\n"
            "Atender os clientes no WhatsApp tirando dúvidas sobre produtos, serviços, "
            "endereço, prazos de entrega e pedidos de forma ágil, calorosa e esclarecedora.\n\n"
            "REGRAS DE OURO:\n"
            "- Fale sempre em Português do Brasil com frases curtas, objetivas e fáceis de ler no celular.\n"
            "- Se não souber uma informação ou se o dado não constar no material de apoio, NUNCA invente: "
            "peça desculpas com cordialidade e informe que um atendente humano irá assumir o atendimento.\n"
            "{off_hours_rule}\n"
            "{extra_rules}\n"
        ),
    },
    "sdr_vendedor": {
        "title": "Vendedor & Qualificador de Clientes",
        "badge": "Vendas & Prospecção",
        "desc": "Recebe leads, qualifica o interesse, descobre orçamento e agenda reuniões ou encaminha para venda.",
        "icon": "🎯",
        "agent_type": "sdr",
        "tools": ["transcribe", "retrieval", "crm_create_deal", "crm_update_deal", "crm_set_follow_up"],
        "base_prompt": (
            "Você é o consultor comercial da empresa {business_name}.\n"
            "O que vendemos: {business_description}\n"
            "Tom de conversa: {tone_text}\n\n"
            "MISSÃO:\n"
            "Receber contatos de pessoas interessadas em nossos produtos/serviços, fazer perguntas amigáveis de "
            "qualificação (necessidade, urgência e interesse) e agendar uma conversa ou apresentar proposta.\n\n"
            "REGRAS DE OURO:\n"
            "- Faça uma pergunta de cada vez para manter a conversa fluida, natural e sem parecer interrogatório.\n"
            "- Nunca force a venda nem conceda descontos arbitrários sem autorização.\n"
            "{extra_rules}\n"
        ),
    },
    "agendador": {
        "title": "Agendador de Horários & Consultas",
        "badge": "Clínicas, Barbearias & Consultorias",
        "desc": "Apresenta serviços e ajuda clientes a escolherem o melhor dia e horário para agendar.",
        "icon": "🗓️",
        "agent_type": "support",
        "tools": ["transcribe", "retrieval", "crm_create_deal", "crm_list_deals"],
        "base_prompt": (
            "Você é o assistente de agendamentos da empresa {business_name}.\n"
            "Serviços oferecidos: {business_description}\n"
            "Tom de conversa: {tone_text}\n\n"
            "MISSÃO:\n"
            "Ajudar o cliente a conhecer os serviços disponíveis, verificar dias e horários convenientes "
            "e registrar a solicitação de agendamento com atenção e rapidez.\n\n"
            "REGRAS DE OURO:\n"
            "- Confirme sempre nome, serviço desejado e horário preferido antes de finalizar.\n"
            "{extra_rules}\n"
        ),
    },
    "recuperador": {
        "title": "Recuperador de Vendas & Pós-Venda",
        "badge": "Retenção & Reengajamento",
        "desc": "Manda mensagem amigável para quem parou de responder propostas ou abandonou compras.",
        "icon": "🔄",
        "agent_type": "sdr",
        "tools": ["transcribe", "retrieval", "crm_update_deal"],
        "base_prompt": (
            "Você é o especialista de relacionamento e pós-venda da empresa {business_name}.\n"
            "Negócio: {business_description}\n"
            "Tom de conversa: {tone_text}\n\n"
            "MISSÃO:\n"
            "Retomar contato com clientes que demonstraram interesse anterior mas não concluíram o pedido, "
            "esclarecendo eventuais dúvidas com gentileza e sem insistência invasiva.\n\n"
            "{extra_rules}\n"
        ),
    },
}

MODEL_KEYS: Dict[str, Dict[str, Any]] = {
    "fast": {
        "model": "openai/gpt-4o-mini",
        "temperature": 0.5,
        "max_tokens": 1024,
        "label": "Rápido & Econômico",
        "description": "Respostas rápidas no WhatsApp em menos de 2 segundos. Ideal para atendimento ágil e baixo custo.",
    },
    "deep": {
        "model": "openai/gpt-4o",
        "temperature": 0.4,
        "max_tokens": 2048,
        "label": "Alta Precisão & Raciocínio",
        "description": "Mais inteligente para interpretações detalhadas, negociações delicadas e catálogos extensos.",
    },
}

TONE_MAP: Dict[str, str] = {
    "amigavel": "Amigável, acolhedor e educado, usando emojis com equilíbrio e bom gosto.",
    "profissional": "Profissional, elegante, polido, respeitoso e objetivo.",
    "direto": "Super conciso, direto ao ponto, ágil e focado na resposta rápida.",
}


def compile_plug_and_play_agent(
    solution_key: str,
    name: Optional[str] = None,
    business_name: str = "",
    business_description: str = "",
    intelligence_level: str = "fast",
    tone: str = "amigavel",
    rules: Optional[List[str]] = None,
    faq_text: str = "",
    business_hours: Optional[str] = None,
    off_hours_behavior: str = "take_note",
) -> Dict[str, Any]:
    """Compila escolhas de alto nível em um payload completo de Agent para o banco do AIOS."""
    sol = PLUG_AND_PLAY_SOLUTIONS.get(solution_key, PLUG_AND_PLAY_SOLUTIONS["whatsapp_atendente"])
    model_cfg = MODEL_KEYS.get(intelligence_level, MODEL_KEYS["fast"])
    tone_text = TONE_MAP.get(tone, TONE_MAP["amigavel"])

    b_name = business_name.strip() or "Nossa Empresa"
    b_desc = business_description.strip() or "produtos e serviços de qualidade"
    b_hours = business_hours.strip() if business_hours else "Segunda a Sexta, das 08h às 18h"

    off_hours_rule = ""
    if off_hours_behavior == "take_note":
        off_hours_rule = (
            f"- Fora do horário comercial ({b_hours}): informe gentilmente que a equipe humana está em descanso "
            "e anote o nome do cliente e a dúvida/pedido para retorno prioritário no próximo dia útil."
        )
    elif off_hours_behavior == "bot_only":
        off_hours_rule = (
            f"- O atendimento automático funciona 24 horas, mas questões que dependem de humanos serão tratadas "
            f"no horário comercial ({b_hours})."
        )

    extra_rules_list = []
    if rules:
        if "no_invent_price" in rules:
            extra_rules_list.append("- NUNCA invente preços, promoções ou prazos que não foram formalmente cadastrados.")
        if "human_handover" in rules:
            extra_rules_list.append(
                "- Se o cliente demonstrar insatisfação, irritação ou pedir explicitamente para falar com uma pessoa, "
                "confirme educadamente que está transferindo para a equipe humana."
            )
        if "confirm_data" in rules:
            extra_rules_list.append("- Sempre confirme o telefone e o nome do cliente antes de registrar qualquer solicitação.")

    if faq_text.strip():
        extra_rules_list.append(f"\nBASE DE PERGUNTAS E RESPOSTAS FREQUENTES DA EMPRESA:\n{faq_text.strip()}")

    prompt = sol["base_prompt"].format(
        business_name=b_name,
        business_description=b_desc,
        tone_text=tone_text,
        business_hours_text=b_hours,
        off_hours_rule=off_hours_rule,
        extra_rules="\n".join(extra_rules_list),
    )

    agent_name = name.strip() if name and name.strip() else f"{sol['title']} — {b_name[:20]}"

    return {
        "name": agent_name,
        "agent_type": sol["agent_type"],
        "system_prompt": prompt,
        "llm_config": {
            "model": model_cfg["model"],
            "temperature": model_cfg["temperature"],
            "max_tokens": model_cfg["max_tokens"],
        },
        "tools": list(sol["tools"]),
        "memory_config": {
            "short_term": {"max_messages": 30},
            "long_term": {"enabled": True, "top_k": 5},
            "episodic": {"enabled": False},
        },
        "governance_config": {
            "autonomy": "autonomous",
            "max_tokens_per_run": 50000,
            "allowed_tools": list(sol["tools"]),
        },
        "extra_data": {
            "simple_config": {
                "solution_key": solution_key,
                "intelligence_level": intelligence_level,
                "business_name": b_name,
                "business_description": b_desc,
                "tone": tone,
                "rules": rules or [],
                "faq_text": faq_text,
                "business_hours": b_hours,
                "off_hours_behavior": off_hours_behavior,
                "created_via": "simple_mode",
            }
        },
    }
