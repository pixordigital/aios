import logging
logger = logging.getLogger(__name__)

def risk_score(connected: bool, fails_24h: int, qr_regenerations: int, http_429: int) -> int:
    score = 0
    if not connected: score += 45
    score += min(30, fails_24h * 6)
    score += min(25, qr_regenerations * 12)
    score += min(20, http_429 * 8)
    return min(100, score)

def should_quarantine(score: int, critical: int = 85) -> bool:
    return score >= critical
