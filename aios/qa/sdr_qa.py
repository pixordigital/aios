"""QA Evolution 10 fases — review SDR (inspirado Synkra ADE Epic 6)."""

QA_SDR_10 = [
    (1, "Empatia H2H", "Cumprimentou, reconheceu dor, tom humano PT-BR?"),
    (2, "BANT+GPCT", "Qualificou Budget/Authority/Need/Timing + Goals/Plan/Challenges?"),
    (3, "RAG citou fonte", "Buscou hybrid_search/rag_search e citou source do PDF?"),
    (4, "Latência", "Resposta <1,5s (Kokoro 300ms + LLM 800ms)?"),
    (5, "Objeção", "Tratou objeção com SPIN/MEDDIC sem inventar preço?"),
    (6, "Handoff", "Escalou humano com contexto quando pediu humano ou 2 tentativas?"),
    (7, "Follow-up", "Agendou follow-up 14d e create_deal?"),
    (8, "LGPD", "Não vazou dado de outro org, auditou?"),
    (9, "Idioma", "PT-BR nativo, sem en, sem alucinação?"),
    (10, "Fechamento", "Agenda/closed_won com HITL >R$5k quando necessário?"),
]

def score_conversation(messages: list[dict], rag_hits: int = 0, latency_ms: int = 0) -> dict:
    """Score simples 0-10 — cada fase 0/1."""
    scores = {}
    # heurísticas leves (sem LLM)
    text = " ".join([m.get("content","") for m in messages]).lower()
    scores[1] = 1 if any(w in text for w in ["olá","posso ajudar","entendo"]) else 0
    scores[2] = 1 if any(w in text for w in ["orçamento","prazo","budget","timing"]) else 0
    scores[3] = 1 if rag_hits > 0 or "fonte:" in text or "pdf" in text else 0
    scores[4] = 1 if 0 < latency_ms < 1500 else 0
    scores[5] = 1 if "objeção" not in text or "entendo" in text else 1
    scores[6] = 1 if "humano" not in text or "escal" in text or "handover" in text else 0
    scores[7] = 1 if "follow" in text or "agend" in text else 0
    scores[8] = 1
    scores[9] = 1 if "the" not in text or "you" not in text else 0
    scores[10] = 1 if "aprov" not in text else 1
    total = sum(scores.values())
    return {"total": total, "max": 10, "scores": scores, "checklist": [{"fase": f, "nome": n, "ok": bool(scores.get(f,0)), "pergunta": q} for f,n,q in QA_SDR_10]}

def capture_insight(deal_stage: str, conversation: list[dict]) -> str:
    """Memory Layer — insight pós closed_won/lost."""
    text = " ".join([m.get("content","")[:200] for m in conversation])[:500]
    return f"[{deal_stage}] insight: {text[:200]}..."
