from dataclasses import dataclass

THRESHOLDS = {
    "monthly_messages": {"warn": 1000, "critical": 5000},
    "ban_risk_score": {"warn": 70, "critical": 85},
    "failed_sends_pct": {"warn": 5, "critical": 15},
}

@dataclass
class MigrationRecommendation:
    should_migrate: bool
    reasons: list[str]
    urgency: str  # low|medium|high|critical

def evaluate(monthly_msgs: int, ban_risk: int, failed_pct: float, is_coexistence: bool = False, is_on_biz_app: bool = False) -> MigrationRecommendation:
    if is_coexistence or is_on_biz_app:
        return MigrationRecommendation(should_migrate=False, reasons=["Coexistence já é Cloud oficial (ban risk ~5) — não migrar"], urgency="low")
    reasons=[]
    urgency="low"
    if monthly_msgs >= THRESHOLDS["monthly_messages"]["critical"]: reasons.append(f"{monthly_msgs} msgs/mês ≥5000 → Cloud API recomendado")
    elif monthly_msgs >= THRESHOLDS["monthly_messages"]["warn"]: reasons.append(f"{monthly_msgs} msgs/mês ≥1000 → considere Cloud API")
    if ban_risk >= THRESHOLDS["ban_risk_score"]["critical"]: reasons.append(f"ban risk {ban_risk} ≥85 → migre crítico")
    elif ban_risk >= THRESHOLDS["ban_risk_score"]["warn"]: reasons.append(f"ban risk {ban_risk} ≥70 → risco alto")
    if failed_pct >= THRESHOLDS["failed_sends_pct"]["critical"]: reasons.append(f"falhas {failed_pct}% ≥15%")
    elif failed_pct >= THRESHOLDS["failed_sends_pct"]["warn"]: reasons.append(f"falhas {failed_pct}% ≥5%")
    should = any(x in r for r in reasons for x in [">=5000","≥85","≥15%"])
    if any("≥85" in r or "≥5000" in r for r in reasons): urgency="critical"
    elif any("≥70" in r or "≥1000" in r for r in reasons): urgency="medium"
    return MigrationRecommendation(should_migrate=should, reasons=reasons, urgency=urgency)
