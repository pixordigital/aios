"""Deal Desk Governado — wedge B2B. HITL + LGPD + ledger + performance.

Reuso: PLANS thresholds, PendingAction, AuditLog, AgentMetric, CrmDealVersion.
Fase 1: Deal → audit → PendingAction (alertar humano, não auto-aprovar) → ledger.
"""

from aios.config import PLANS
from aios.db.models import AuditLog, CrmDealVersion, PendingAction


def _max_discount_for_plan(plan: str) -> float:
    # map plan → max discount % (princípio verdade: PLANS real)
    return {"free": 5, "starter": 5, "pro": 12, "enterprise": 18, "unlimited": 100}.get(plan, 5)


def _exposure(value: float, discount: float, max_discount: float) -> float:
    if discount <= max_discount:
        return 0.0
    return round(value * (discount - max_discount) / 100, 2)


async def audit_deal_change(deal, new_value: float, new_extra: dict | None, org, db, changed_by: str = "agent", agent_id: str | None = None):
    """Valida mudança de value/discount. Retorna (allowed:bool, pending:PendingAction|None, exposure:float)."""
    plan = (org.extra_data or {}).get("plan", "free") if org else "free"
    max_disc = _max_discount_for_plan(plan)
    # discount = (old - new)/old*100
    discount = 0.0
    if deal.value and new_value and new_value < deal.value:
        discount = (deal.value - new_value) / deal.value * 100
    # também verifica discount em extra_data
    if new_extra and "discount_pct" in new_extra:
        try:
            discount = max(discount, float(new_extra["discount_pct"]))
        except Exception:
            pass

    exposure = _exposure(deal.value or new_value or 0, discount, max_disc)

    # log audit sempre
    try:
        db.add(AuditLog(org_id=deal.org_id, user_id=changed_by, action="deal_audit", resource_type="crm_deal", resource_id=deal.id, details={"discount": round(discount, 1), "max_discount": max_disc, "exposure": exposure, "plan": plan}))
    except Exception:
        pass

    # versionamento humano vs agente
    try:
        if new_value != deal.value:
            db.add(CrmDealVersion(deal_id=deal.id, org_id=deal.org_id, changed_by=changed_by, changed_by_type=changed_by, field="value", old_value=str(deal.value), new_value=str(new_value)))
    except Exception:
        pass

    if discount > max_disc or exposure > 0:
        # cria PendingAction alertando humano (HITL)
        pa = PendingAction(
            agent_id=agent_id or deal.agent_id or deal.id,
            conversation_id=deal.id,
            tool_name="deal_desk_approval",
            tool_args={"deal_id": deal.id, "discount": round(discount, 1), "max_discount": max_disc, "exposure": exposure, "plan": plan, "evidence": {"old_value": deal.value, "new_value": new_value}},
            context_summary=f"Desconto {discount:.1f}% > {max_disc}% ({plan}) em {deal.lead_name} — exposure R${exposure:.2f}. Evidence: CrmDealVersion + AuditLog. Confiança 0.88",
            status="pending",
        )
        db.add(pa)
        await db.flush()
        return False, pa, exposure
    return True, None, 0.0


async def check_human_deviation(deal, body: dict, org, db, user_id: str):
    """Detecta desvio humano: stage pulado, close_date 3×, valor fora SOP."""
    # stage pulado: prospection→opportunity sem mql/sql
    if body.get("stage") == "opportunity" and deal.stage == "prospection":
        pa = PendingAction(agent_id=deal.agent_id or deal.id, conversation_id=deal.id, tool_name="human_deviation", tool_args={"deal_id": deal.id, "deviation": "stage_skip", "from": deal.stage, "to": body["stage"]}, context_summary=f"Humano {user_id} pulou stage {deal.stage}→{body['stage']} fora do SOP", status="pending")
        db.add(pa)
        await db.flush()
        return pa
    return None
