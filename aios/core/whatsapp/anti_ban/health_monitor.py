from .ban_detector import risk_score
def compute(instance: str, connected: bool, fails_24h: int, qr: int, r429: int) -> dict:
    score = risk_score(connected, fails_24h, qr, r429)
    level = "green" if score < 40 else "yellow" if score < 70 else "red"
    return {"instance": instance, "risk": score, "level": level, "quarantined": score>=85}
