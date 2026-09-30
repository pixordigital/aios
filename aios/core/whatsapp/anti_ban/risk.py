"""Ban-risk scoring from real Evolution signals.

The previous implementation was a stub: four caller-supplied integers, no data
source, and nothing ever called it. This reads the whatsapp_events feed that
the send path actually writes and turns it into a score plus the reasons behind
it, so the dashboard can say *why* a number is at risk instead of showing an
opaque number.

Scoring is deliberately conservative: it is meant to warn early, not to claim
WhatsApp's own risk model is knowable from the outside. Signals WhatsApp does
not publish (its classifiers, device reputation) are invisible here.
"""

from dataclasses import dataclass, field

# A signal only counts after this many are seen; one 429 is noise, five is a
# pattern. Keeps the score from flapping on a single transient error.
THRESHOLDS = {"http_429": 3, "http_403": 1, "ban_signal": 1, "disconnect": 2}

WEIGHTS = {"http_403": 30, "ban_signal": 35, "http_429": 12, "disconnect": 15, "opted_out": 2}

# Per-instance send velocity matters: running hot against the warmup curve is
# the single biggest self-inflicted ban risk on an unofficial client.
VELOCITY_WEIGHT = 20


@dataclass
class RiskReport:
    score: int = 0
    level: str = "green"
    quarantined: bool = False
    drivers: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    advice: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "level": self.level,
            "quarantined": self.quarantined,
            "drivers": self.drivers,
            "counts": self.counts,
            "advice": self.advice,
        }


ADVICE = {
    "http_403": "Bloqueios 403 do WhatsApp: pare de enviar. Um 403 é sinal de número comprometido, não de mensagem inválida.",
    "ban_signal": "Sinal de ban ativo. Nenhum envio deve sair até o número voltar a conectar.",
    "http_429": "Rate limit do WhatsApp. Reduza o ritmo; enviar no limite é o caminho mais curto para o ban.",
    "disconnect": "Quedas repetidas. Costuma acompanhar bloqueio upstream — cheque o Evolution antes de continuar.",
    "opted_out": "Taxa alta de opt-out: sua mensagem está irritando quem recebe. Revise o conteúdo e a lista.",
    "velocity": "Enviando acima do_curve de aquecimento. Respeite a curva por instância nas primeiras semanas.",
}


def score_from_events(counts: dict, connected: bool = True, velocity_ratio: float = 0.0) -> RiskReport:
    """Build a report from event counts in a lookback window.

    counts: {"http_403": n, "ban_signal": n, "http_429": n, "disconnect": n, "opted_out": n}
    velocity_ratio: sends_today / warmup_daily_limit (1.0 == exactly at the cap)
    """
    score = 0
    drivers: list[str] = []
    seen = {}

    for kind, threshold in THRESHOLDS.items():
        n = int(counts.get(kind, 0) or 0)
        seen[kind] = n
        if n < threshold:
            continue
        # Scale past the threshold, then cap, so 50 errors is not 50x worse.
        weight = WEIGHTS[kind]
        over = min(1.0, (n - threshold + 1) / max(threshold, 1))
        score += int(weight * (0.5 + 0.5 * over))
        drivers.append(kind)

    if velocity_ratio > 1.0:
        over = min(2.0, velocity_ratio)
        score += int(VELOCITY_WEIGHT * min(1.0, (over - 1.0) / 1.0))
        drivers.append("velocity")

    if not connected:
        score += 20
        drivers.append("disconnected")

    score = max(0, min(100, score))
    level = "green" if score < 40 else "yellow" if score < 70 else "red"

    # Advice is ordered by severity so the dashboard leads with what matters.
    order = ["ban_signal", "http_403", "disconnect", "velocity", "http_429", "opted_out", "disconnected"]
    advice = [ADVICE[d] for d in order if d in drivers and d in ADVICE]

    return RiskReport(
        score=score,
        level=level,
        quarantined=score >= 85,
        drivers=drivers,
        counts=seen,
        advice=advice,
    )
