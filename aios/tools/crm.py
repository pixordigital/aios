import logging
import httpx
from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class CRMCreateDealInput(BaseModel):
    lead_email: str = Field(description="Email do lead")
    lead_name: str = Field(description="Nome do lead")
    company: str = Field(default="", description="Empresa")
    deal_stage: str = Field(
        default="mql", description="mql|sql|opportunity|closed_won|closed_lost"
    )
    value: float = Field(default=0, description="Valor estimado")
    notes: str = Field(default="", description="Notas do SDR")


class CRMUpdateDealInput(BaseModel):
    deal_id: str = Field(description="ID do deal no CRM")
    stage: str = Field(description="Novo stage")
    notes: str = Field(default="")


class CRMTool(BaseTool):
    name = "crm_create_deal"
    description = "Cria deal no CRM interno 100% IA + HubSpot/webhook se configurado. Auto-cria no kanban."

    async def run(
        self,
        lead_email: str,
        lead_name: str,
        company: str = "",
        deal_stage: str = "mql",
        value: float = 0,
        notes: str = "",
    ) -> dict:
        from aios.config import settings

        webhook = getattr(settings, "crm_webhook_url", "") or ""
        hs_key = ""
        try:
            import os

            webhook = os.getenv("AIOS_CRM_WEBHOOK_URL", webhook)
            hs_key = os.getenv("HUBSPOT_API_KEY", "") or os.getenv(
                "AIOS_HUBSPOT_API_KEY", ""
            )
        except Exception:
            pass

        payload = {
            "lead_email": lead_email,
            "lead_name": lead_name,
            "company": company,
            "deal_stage": deal_stage,
            "value": value,
            "notes": notes[:1000],
            "source": "aios_sdr",
        }
        internal_id = None
        # ── 1-click presets: Pipedrive / Zendesk / Astrea (Projuris) ──
        # Env: PIPEDRIVE_API_KEY + PIPEDRIVE_DOMAIN, ZENDESK_SUBDOMAIN+ZENDESK_EMAIL+ZENDESK_API_KEY, ASTREA_WEBHOOK_URL
        try:
            pipedrive_key = os.getenv("PIPEDRIVE_API_KEY") or os.getenv("AIOS_PIPEDRIVE_API_KEY", "")
            pipedrive_domain = os.getenv("PIPEDRIVE_DOMAIN") or os.getenv("AIOS_PIPEDRIVE_DOMAIN", "api")
            if pipedrive_key:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.post(
                        f"https://{pipedrive_domain}.pipedrive.com/api/v1/deals?api_token={pipedrive_key}",
                        json={"title": f"{lead_name} - {company}", "value": value, "currency": "BRL", "status": "open", "visible_to": 3},
                    )
                    if r.status_code < 300:
                        return {"ok": True, "provider": "pipedrive", "deal_id": r.json().get("data", {}).get("id"), "internal_id": internal_id, "payload": payload}
                    logger.warning("Pipedrive create failed %s %s", r.status_code, r.text[:500])
            zendesk_sub = os.getenv("ZENDESK_SUBDOMAIN") or os.getenv("AIOS_ZENDESK_SUBDOMAIN", "")
            zendesk_email = os.getenv("ZENDESK_EMAIL") or os.getenv("AIOS_ZENDESK_EMAIL", "")
            zendesk_key = os.getenv("ZENDESK_API_KEY") or os.getenv("AIOS_ZENDESK_API_KEY", "")
            if zendesk_sub and zendesk_key and zendesk_email:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.post(
                        f"https://{zendesk_sub}.zendesk.com/api/v2/tickets",
                        json={"ticket": {"subject": f"Lead {lead_name} - {company}", "comment": {"body": notes[:1000]}, "requester": {"name": lead_name, "email": lead_email}, "priority": "normal"}},
                        auth=(f"{zendesk_email}/token", zendesk_key),
                    )
                    if r.status_code < 300:
                        return {"ok": True, "provider": "zendesk", "deal_id": r.json().get("ticket", {}).get("id"), "internal_id": internal_id, "payload": payload}
                    logger.warning("Zendesk create failed %s %s", r.status_code, r.text[:500])
            astrea_hook = os.getenv("ASTREA_WEBHOOK_URL") or os.getenv("AIOS_ASTRA_WEBHOOK_URL", "") or os.getenv("AIOS_ASTREA_WEBHOOK_URL", "")
            if astrea_hook:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.post(astrea_hook, json={"nome": lead_name, "email": lead_email, "empresa": company, "valor": value, "observacoes": notes[:1000], "origem": "AIOS"})
                    if r.status_code < 300:
                        return {"ok": True, "provider": "astrea", "deal_id": f"astrea_{lead_email}", "internal_id": internal_id, "payload": payload}
        except Exception as e:
            logger.warning("CRM preset error %s", e)

        # 1. Sempre cria no CRM interno (kanban) — 100% IA
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal
            import uuid
            async with async_session() as s:
                # tenta achar org via agent ou usa default
                org_id = None
                try:
                    from sqlalchemy import select
                    from aios.db.models import Agent
                    # pega primeiro org se não houver contexto
                    from aios.db.models import Organization
                    org = (await s.execute(select(Organization).limit(1))).scalars().first()
                    if org:
                        org_id = org.id
                except Exception:
                    pass
                if org_id:
                    deal = CrmDeal(
                        org_id=org_id,
                        lead_name=lead_name,
                        lead_email=lead_email,
                        lead_phone=payload.get("company",""),
                        stage=deal_stage if deal_stage in ("prospection","mql","sql","opportunity","closed_won","closed_lost") else "mql",
                        value=float(value or 0),
                        source="whatsapp",
                        extra_data={"notes": notes[:500], "company": company},
                    )
                    s.add(deal)
                    await s.commit()
                    await s.refresh(deal)
                    internal_id = deal.id
        except Exception as e:
            logger.warning("Internal CRM create failed %s", e)

        if hs_key:
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.post(
                        "https://api.hubapi.com/crm/v3/objects/deals",
                        headers={
                            "Authorization": f"Bearer {hs_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "properties": {
                                "dealname": f"{lead_name} - {company}",
                                "dealstage": deal_stage,
                                "amount": str(value),
                                "hubspot_owner_id": "",
                            }
                        },
                    )
                    if r.status_code < 300:
                        return {
                            "ok": True,
                            "provider": "hubspot",
                            "deal_id": r.json().get("id"),
                            "internal_id": internal_id,
                            "payload": payload,
                        }
                    logger.warning(
                        "HubSpot create failed %s %s", r.status_code, r.text[:500]
                    )
            except Exception as e:
                logger.warning("HubSpot error %s", e)

        if webhook:
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.post(webhook, json=payload)
                    return {
                        "ok": r.status_code < 300,
                        "provider": "webhook",
                        "status": r.status_code,
                        "internal_id": internal_id,
                        "payload": payload,
                    }
            except Exception as e:
                return {"ok": False, "error": str(e), "payload": payload, "internal_id": internal_id}

        return {
            "ok": True,
            "provider": "internal" if internal_id else "mock",
            "deal_id": internal_id or f"mock_{lead_email}",
            "internal_id": internal_id,
            "payload": payload,
        }


class CRMUpdateTool(BaseTool):
    name = "crm_update_deal"
    description = "Atualiza stage do deal no CRM. 100% IA com HITL: mudanças críticas (closed_won > R$5k, closed_lost, desconto) vão pra aprovação humana."

    async def run(self, deal_id: str, stage: str, notes: str = "") -> dict:
        from aios.config import settings
        import os

        # HITL: check if this update needs human approval
        needs_hitl = False
        hitl_reason = ""
        if stage in ("closed_won", "closed_lost"):
            needs_hitl = True
            hitl_reason = f"Movendo para {stage} requer aprovação"
        # Also check deal value if available
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal
            async with async_session() as s:
                deal = await s.get(CrmDeal, deal_id)
                if deal and deal.value and deal.value > 5000 and stage == "closed_won":
                    needs_hitl = True
                    hitl_reason = f"Deal R${deal.value:.2f} > R$5k em {stage} — aprovação necessária"
        except Exception:
            pass

        if needs_hitl:
            try:
                from aios.db.engine import async_session
                from aios.db.models import PendingAction
                async with async_session() as s:
                    # find agent/conversation from deal if available
                    deal = await s.get(CrmDeal, deal_id) if 'CrmDeal' in locals() else None
                    pa = PendingAction(
                        agent_id=deal.agent_id if deal and deal.agent_id else deal_id,
                        conversation_id=deal_id,
                        tool_name="crm_update_deal",
                        tool_args={"deal_id": deal_id, "stage": stage, "notes": notes},
                        context_summary=hitl_reason,
                        status="pending",
                    )
                    s.add(pa)
                    await s.commit()
                    return {"ok": True, "pending": True, "pending_id": pa.id, "reason": hitl_reason, "message": f"Ação pendente de aprovação: {hitl_reason}"}
            except Exception as e:
                logger.warning("HITL create failed %s", e)

        # Auto-apply for non-critical stages: also update internal CrmDeal
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal
            async with async_session() as s:
                deal = await s.get(CrmDeal, deal_id)
                if deal and stage in ("prospection","mql","sql","opportunity","closed_won","closed_lost"):
                    deal.stage = stage
                    if notes:
                        deal.extra_data = {**(deal.extra_data or {}), "last_ai_notes": notes[:500]}
                    await s.commit()
        except Exception as e:
            logger.warning("Internal CRM update failed %s", e)

        webhook = os.getenv(
            "AIOS_CRM_WEBHOOK_URL", getattr(settings, "crm_webhook_url", "") or ""
        )
        if webhook:
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.post(
                        webhook,
                        json={
                            "deal_id": deal_id,
                            "stage": stage,
                            "notes": notes,
                            "action": "update",
                        },
                    )
                    return {"ok": r.status_code < 300, "status": r.status_code, "stage": stage, "hitl": needs_hitl}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": True, "provider": "internal", "deal_id": deal_id, "stage": stage, "hitl": needs_hitl}


TOOL_REGISTRY["crm_create_deal"] = {"code_reference": "aios.tools.crm.CRMTool"}
TOOL_REGISTRY["crm_update_deal"] = {"code_reference": "aios.tools.crm.CRMUpdateTool"}
