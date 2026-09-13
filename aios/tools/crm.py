import logging
from sqlalchemy import text
import httpx
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone

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
    score: int = Field(default=0, description="lead_score 0-100 para auto stage")
    pipeline: str = Field(default="default", description="pipeline/unidade")


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
        score: int = 0,
        pipeline: str = "default",
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

        # C3: score → stage automático
        try:
            sc = int(score or 0)
            if sc >= 85:
                deal_stage = "sql"
            elif sc >= 70:
                deal_stage = "mql"
            elif sc > 0 and sc < 20:
                deal_stage = "prospection"
        except Exception:
            pass
        # 1. Sempre cria no CRM interno (kanban) — 100% IA com deduplicação + validação + lock
        # Validação
        if not lead_email or "@" not in lead_email:
            return {"ok": False, "error": "lead_email inválido"}
        if not lead_name or len(lead_name.strip()) < 2:
            return {"ok": False, "error": "lead_name obrigatório (≥2 chars)"}
        if value and float(value) < 0:
            return {"ok": False, "error": "value não pode ser negativo"}
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal, CrmDealVersion
            import uuid
            from sqlalchemy import select as _sel
            async with async_session() as s:
                # tenta achar org via agent ou usa default
                org_id = None
                try:
                    from sqlalchemy import select
                    from aios.db.models import Agent
                    from aios.db.models import Organization
                    org = (await s.execute(select(Organization).limit(1))).scalars().first()
                    if org:
                        org_id = org.id
                except Exception:
                    pass
                if org_id:
                    # Deduplicação: verifica deal ativo para mesmo email (org_id lock)
                    existing = (await s.execute(_sel(CrmDeal).where(CrmDeal.org_id == org_id, CrmDeal.lead_email == lead_email, CrmDeal.stage.notin_(["closed_won", "closed_lost"])))).scalars().first()
                    if existing:
                        logger.info("CRM deduplicação: deal ativo %s para %s", existing.id, lead_email)
                        return {"ok": True, "provider": "internal-dedup", "deal_id": existing.id, "internal_id": existing.id, "payload": payload, "dedup": True}
                    # Lock por org_id para evitar race (SELECT FOR UPDATE)
                    try:
                        await s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": abs(hash(org_id)) % 2147483647})
                    except Exception:
                        pass
                    # C10: Auto-calculate probability and close_date based on score + stage
                    sc = int(score or 0)
                    prob = 0.0
                    close_dt = None
                    if deal_stage == "closed_won":
                        prob = 100.0
                        close_dt = datetime.now(timezone.utc)
                    elif deal_stage == "closed_lost":
                        prob = 0.0
                        close_dt = datetime.now(timezone.utc)
                    elif deal_stage == "opportunity":
                        prob = min(80 + (sc / 5), 95)
                        close_dt = datetime.now(timezone.utc) + timedelta(days=14)
                    elif deal_stage == "sql":
                        prob = min(50 + (sc / 3), 75)
                        close_dt = datetime.now(timezone.utc) + timedelta(days=30)
                    elif deal_stage == "mql":
                        prob = min(20 + (sc / 4), 45)
                        close_dt = datetime.now(timezone.utc) + timedelta(days=60)
                    else:  # prospection
                        prob = min(sc / 5, 15)
                        close_dt = datetime.now(timezone.utc) + timedelta(days=90)
                    
                    deal = CrmDeal(
                        org_id=org_id,
                        lead_name=lead_name,
                        lead_email=lead_email,
                        lead_phone=payload.get("company",""),
                        stage=deal_stage if deal_stage in ("prospection","mql","sql","opportunity","closed_won","closed_lost") else "mql",
                        value=float(value or 0),
                        source="whatsapp",
                        score=int(score or 0),
                        pipeline=(pipeline or "default")[:50],
                        probability=round(prob, 1),
                        close_date=close_dt,
                        extra_data={"notes": notes[:500], "company": company},
                    )
                    s.add(deal)
                    await s.flush()
                    # Versionamento: cria v1
                    try:
                        ver = CrmDealVersion(deal_id=deal.id, org_id=org_id, changed_by=None, changed_by_type="agent", field="create", old_value="", new_value=f"{lead_email}|{deal_stage}|{value}", extra_data={"company": company})
                        s.add(ver)
                    except Exception:
                        pass
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

        # Auto-apply for non-critical stages: also update internal CrmDeal com lock + versionamento
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal, CrmDealVersion
            from sqlalchemy import text as _text2
            async with async_session() as s:
                # Lock por org_id
                deal = await s.get(CrmDeal, deal_id)
                if deal:
                    try:
                        await s.execute(_text2("SELECT pg_advisory_xact_lock(:k)"), {"k": abs(hash(deal.org_id)) % 2147483647})
                    except Exception:
                        pass
                if deal and stage in ("prospection","mql","sql","opportunity","closed_won","closed_lost"):
                    old_stage = deal.stage
                    old_value = deal.value
                    deal.stage = stage
                    if notes:
                        deal.extra_data = {**(deal.extra_data or {}), "last_ai_notes": notes[:500]}
                    # C10: Update probability and close_date based on new stage
                    sc = deal.score or 0
                    if stage == "closed_won":
                        deal.probability = 100.0
                        deal.close_date = datetime.now(timezone.utc)
                    elif stage == "closed_lost":
                        deal.probability = 0.0
                        deal.close_date = datetime.now(timezone.utc)
                    elif stage == "opportunity":
                        deal.probability = min(80 + (sc / 5), 95)
                        deal.close_date = datetime.now(timezone.utc) + timedelta(days=14)
                    elif stage == "sql":
                        deal.probability = min(50 + (sc / 3), 75)
                        deal.close_date = datetime.now(timezone.utc) + timedelta(days=30)
                    elif stage == "mql":
                        deal.probability = min(20 + (sc / 4), 45)
                        deal.close_date = datetime.now(timezone.utc) + timedelta(days=60)
                    else:  # prospection
                        deal.probability = min(sc / 5, 15)
                        deal.close_date = datetime.now(timezone.utc) + timedelta(days=90)
                    deal.probability = round(deal.probability, 1)
                    # Versionamento
                    try:
                        ver = CrmDealVersion(deal_id=deal.id, org_id=deal.org_id, changed_by=None, changed_by_type="agent", field="stage", old_value=str(old_stage), new_value=str(stage), extra_data={"old_value": str(old_value), "new_value": str(deal.value)})
                        s.add(ver)
                        if old_value != deal.value:
                            ver2 = CrmDealVersion(deal_id=deal.id, org_id=deal.org_id, changed_by=None, changed_by_type="agent", field="value", old_value=str(old_value), new_value=str(deal.value))
                            s.add(ver2)
                    except Exception:
                        pass
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


class CRMMergeDealsInput(BaseModel):
    lead_email: str = Field(description="Email do lead para buscar duplicados")
    keep_strategy: str = Field(default="oldest", description="oldest|highest_value|newest - qual deal manter")


class CRMMergeTool(BaseTool):
    name = "crm_merge_deals"
    description = "Mescla deals duplicados do mesmo lead_email na mesma org. Mantém 1 deal e deleta os outros."

    async def run(self, lead_email: str, keep_strategy: str = "oldest") -> dict:
        if not lead_email or "@" not in lead_email:
            return {"ok": False, "error": "lead_email inválido"}
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal, CrmDealVersion, Organization
            from sqlalchemy import select as _sel
            import uuid
            async with async_session() as s:
                org = (await s.execute(_sel(Organization).limit(1))).scalars().first()
                if not org:
                    return {"ok": False, "error": "Org não encontrada"}
                org_id = org.id
                
                # Find all deals with same email
                deals = (await s.execute(_sel(CrmDeal).where(
                    CrmDeal.org_id == org_id, 
                    CrmDeal.lead_email == lead_email
                ).order_by(CrmDeal.created_at))).scalars().all()
                
                if len(deals) <= 1:
                    return {"ok": True, "merged": 0, "message": "Nenhum duplicado encontrado", "deals": [d.id for d in deals]}
                
                # Choose which to keep
                if keep_strategy == "highest_value":
                    keep_deal = max(deals, key=lambda d: d.value or 0)
                elif keep_strategy == "newest":
                    keep_deal = max(deals, key=lambda d: d.created_at)
                else:  # oldest
                    keep_deal = min(deals, key=lambda d: d.created_at)
                
                other_deals = [d for d in deals if d.id != keep_deal.id]
                merged_count = 0
                combined_notes = []
                total_value = keep_deal.value or 0
                
                # Lock
                try:
                    from sqlalchemy import text
                    await s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": abs(hash(org_id)) % 2147483647})
                except Exception:
                    pass
                
                for d in other_deals:
                    # Combine notes
                    if d.extra_data and d.extra_data.get("notes"):
                        combined_notes.append(f"[merged from {d.id[:8]}] {d.extra_data['notes']}")
                    # Track value
                    total_value = max(total_value, d.value or 0)
                    # Version record for merge
                    try:
                        ver = CrmDealVersion(deal_id=keep_deal.id, org_id=org_id, changed_by=None, changed_by_type="system", field="merge", old_value=d.id, new_value=keep_deal.id, extra_data={"merged_deal_id": d.id, "merged_stage": d.stage, "merged_value": d.value})
                        s.add(ver)
                    except Exception:
                        pass
                    # Delete merged deal
                    await s.delete(d)
                    merged_count += 1
                
                # Update kept deal with combined data
                if combined_notes:
                    existing_notes = keep_deal.extra_data.get("notes", "") if keep_deal.extra_data else ""
                    keep_deal.extra_data = {**(keep_deal.extra_data or {}), "notes": (existing_notes + "\n" if existing_notes else "") + "\n".join(combined_notes)}
                keep_deal.value = total_value
                await s.commit()
                
                return {"ok": True, "merged": merged_count, "kept_deal_id": keep_deal.id, "deals_before": len(deals), "message": f"Mesclados {merged_count} duplicados no deal {keep_deal.id[:8]}"}
        except Exception as e:
            logger.warning("CRM merge failed %s", e)
            return {"ok": False, "error": str(e)}


TOOL_REGISTRY["crm_create_deal"] = {"code_reference": "aios.tools.crm.CRMTool"}
TOOL_REGISTRY["crm_update_deal"] = {"code_reference": "aios.tools.crm.CRMUpdateTool"}
TOOL_REGISTRY["crm_merge_deals"] = {"code_reference": "aios.tools.crm.CRMMergeTool"}
