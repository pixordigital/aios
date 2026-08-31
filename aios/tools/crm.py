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
    description = "Cria/atualiza deal no CRM (HubSpot/RD genérico via webhook). Usa AIOS_CRM_WEBHOOK_URL ou HubSpot API se configurado."

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
        from aios.core.secrets import get_org_secrets

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
                        "payload": payload,
                    }
            except Exception as e:
                return {"ok": False, "error": str(e), "payload": payload}

        return {
            "ok": True,
            "provider": "mock",
            "deal_id": f"mock_{lead_email}",
            "payload": payload,
            "note": "Configure AIOS_CRM_WEBHOOK_URL ou HUBSPOT_API_KEY para CRM real",
        }


class CRMUpdateTool(BaseTool):
    name = "crm_update_deal"
    description = "Atualiza stage do deal no CRM"

    async def run(self, deal_id: str, stage: str, notes: str = "") -> dict:
        from aios.config import settings
        import os

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
                    return {"ok": r.status_code < 300, "status": r.status_code}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": True, "provider": "mock", "deal_id": deal_id, "stage": stage}


TOOL_REGISTRY["crm_create_deal"] = {"code_reference": "aios.tools.crm.CRMTool"}
TOOL_REGISTRY["crm_update_deal"] = {"code_reference": "aios.tools.crm.CRMUpdateTool"}
