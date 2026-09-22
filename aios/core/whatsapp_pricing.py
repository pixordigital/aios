"""WhatsApp 2026 pricing BR (per-message, sem Meta Agent).

Rates BRL por categoria (exemplo BR):
- marketing 0.0627, utility 0.0042, authentication 0.0042, service 0.0042
Filtrado de whatsappbusiness.com rate card. Volume tiers omitido no MVP (todo em tier 0).
Free: 1.000 service/mês + 72h entry-point (Click-to-WA) = 0.
A partir de 01/10/2026: service e utility dentro de janela passam a ser cobrados (sem tier p/ service).
Twilio $0.005/msg sempre (handle).
"""

RATES_BR = {
    "marketing": 0.0627,
    "utility": 0.0042,
    "authentication": 0.0042,
    "service": 0.0042,
}

TWILIO_PER_MSG_BRL = 0.005 * 5.5  # USD*5.5 p/ BRL estimado
FREE_SERVICE_MONTHLY = 1000
ENTRY_POINT_HOURS = 72
OCT_2026_CUTOFF = "2026-10-01"

# custo criação template aprox (uma vez)
TEMPLATE_CREATION_COST_BRL = 0.0  # Meta não cobra criação, só entrega


def whatsapp_cost_for_messages(messages: list[dict], after_oct: bool = False) -> dict:
    """
    messages: [{category: marketing|utility|authentication|service, inside_window: bool, is_entry_point: bool}]
    after_oct: se True, service e utility dentro de janela são cobrados (regra 01/10/2026)
    Retorna {total_brl, meta_brl, twilio_brl, split, free_service_used}
    """
    split = {"marketing": 0, "utility": 0, "authentication": 0, "service": 0}
    meta_brl = 0.0
    free_service_remaining = FREE_SERVICE_MONTHLY
    for m in messages:
        cat = m.get("category", "service")
        inside = m.get("inside_window", False)
        is_entry = m.get("is_entry_point", False)
        if is_entry:
            continue  # 72h free
        if cat == "service":
            if not after_oct and inside:
                # até 30/09 grátis dentro de janela
                if free_service_remaining > 0:
                    free_service_remaining -= 1
                    continue
                # além de 1000, mesmo dentro janela antes era grátis? Mantém free até 30/09
                continue
            # após 01/10 ou fora janela: cobra, mas abate 1000 free
            if free_service_remaining > 0 and inside:
                free_service_remaining -= 1
                continue
            rate = RATES_BR.get(cat, 0.0042)
            meta_brl += rate
            split[cat] += 1
        elif cat == "utility" and inside and not after_oct:
            continue  # grátis até 30/09
        else:
            rate = RATES_BR.get(cat, 0.0627 if cat == "marketing" else 0.0042)
            meta_brl += rate
            split[cat] += 1
    twilio_brl = len(messages) * TWILIO_PER_MSG_BRL
    # só cobra twilio se não foi entry_point free? Twilio cobra sempre $0.005 mesmo dentro janela, exceto entry_point?
    # Simplifica: entry_point já foi skipado, então twilio só para billable msgs
    billable_count = sum(split.values())
    twilio_brl = billable_count * 0.005 * 5.5
    total_brl = round(meta_brl + twilio_brl, 4)
    return {
        "total_brl": total_brl,
        "meta_brl": round(meta_brl, 4),
        "twilio_brl": round(twilio_brl, 4),
        "split": split,
        "free_service_remaining": free_service_remaining,
        "billable_count": billable_count,
    }


def estimate_creation_cost(agent_type: str, model: str = "openai/gpt-4o-mini", trial_tokens: int = 3000) -> float:
    """Custo criação agente: tokens de teste × modelo. Automático."""
    from aios.core.tracing import estimate_cost

    return round(estimate_cost(model, trial_tokens) * 5.5, 2)  # BRL


def get_rates(country: str = "BR") -> dict:
    if country == "BR":
        return {"country": "BR", "currency": "BRL", "rates": RATES_BR, "twilio_per_msg_brl": round(0.005 * 5.5, 4), "free_service_monthly": FREE_SERVICE_MONTHLY, "entry_point_hours": ENTRY_POINT_HOURS, "oct_cutoff": OCT_2026_CUTOFF}
    return {"country": country, "rates": RATES_BR, "twilio_per_msg_brl": round(0.005 * 5.5, 4)}
