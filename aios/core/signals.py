"""Sinais-lite — score de timing 0-100 com dado interno (sem provedor externo).

Origem (quem) + recência (quando) + tentativas + estágio + valor.
Fila do dia = deals abertos ordenados por timing desc.
"""

from datetime import datetime, timezone

SOURCE_WEIGHT = {
    "form": 30,
    "whatsapp": 25,
    "inbound": 25,
    "indicacao": 20,
    "site": 15,
    "import": 5,
    "lista_fria": 0,
    "cold": 0,
}

STAGE_WEIGHT = {
    "opportunity": 20,
    "sql": 15,
    "mql": 10,
    "prospection": 5,
}

OPEN_STAGES = ("prospection", "mql", "sql", "opportunity")


def timing_score(deal, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    score = 0
    reasons = []
    source = (deal.source or "").lower()
    sw = SOURCE_WEIGHT.get(source, 5)
    score += sw
    reasons.append(f"origem {source or '?'} +{sw}")
    updated = deal.updated_at
    if updated and updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    hours = (now - updated).total_seconds() / 3600 if updated else 9999
    if hours <= 1:
        score += 30
        reasons.append("quente <1h +30")
    elif hours <= 24:
        score += 20
        reasons.append("recente <24h +20")
    elif hours <= 72:
        score += 10
        reasons.append("<72h +10")
    extra = deal.extra_data or {}
    attempts = int(extra.get("attempts", 0) or 0)
    if attempts == 0:
        score += 10
        reasons.append("nunca tocado +10")
    elif attempts >= 5:
        score -= 10
        reasons.append(f"{attempts} tentativas -10")
    stw = STAGE_WEIGHT.get(deal.stage, 0)
    score += stw
    if stw:
        reasons.append(f"estágio {deal.stage} +{stw}")
    if (deal.value or 0) > 0:
        score += 5
        reasons.append("com valor +5")
    score = max(0, min(100, score))
    return {"timing": score, "reasons": reasons, "hours_since_touch": round(hours, 1), "attempts": attempts}


def rank_queue(deals, limit: int = 20, now: datetime | None = None) -> list[dict]:
    ranked = []
    for d in deals:
        if d.stage not in OPEN_STAGES:
            continue
        s = timing_score(d, now)
        ranked.append({"deal": d, **s})
    ranked.sort(key=lambda r: r["timing"], reverse=True)
    return ranked[:limit]
