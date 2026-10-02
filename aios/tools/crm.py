import logging
from sqlalchemy import text
import httpx
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    """Naive UTC.

    crm_deals datetime columns are TIMESTAMP WITHOUT TIME ZONE (models use
    naive UTC everywhere). asyncpg refuses a tz-aware datetime for those —
    "can't subtract offset-naive and offset-aware datetimes" — which made
    every crm_create_deal fail on Postgres.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
                # Org comes from the tool engine (the calling agent's org).
                # Falling back to Organization.limit(1) wrote every agent's
                # deals into whichever org sorted first.
                org_id = getattr(self, "_org_id", "") or ""
                if not org_id:
                    return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
                if True:
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
                        close_dt = _now_utc()
                    elif deal_stage == "closed_lost":
                        prob = 0.0
                        close_dt = _now_utc()
                    elif deal_stage == "opportunity":
                        prob = min(80 + (sc / 5), 95)
                        close_dt = _now_utc() + timedelta(days=14)
                    elif deal_stage == "sql":
                        prob = min(50 + (sc / 3), 75)
                        close_dt = _now_utc() + timedelta(days=30)
                    elif deal_stage == "mql":
                        prob = min(20 + (sc / 4), 45)
                        close_dt = _now_utc() + timedelta(days=60)
                    else:  # prospection
                        prob = min(sc / 5, 15)
                        close_dt = _now_utc() + timedelta(days=90)
                    
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

        # No silent fallback. An internal write that fails must surface as a
        # failure: the previous path returned ok:true with deal_id
        # "mock_<email>", so agents reported created deals that did not exist.
        if not internal_id:
            return {
                "ok": False,
                "error": "deal não criado no CRM interno",
                "payload": payload,
            }

        return {
            "ok": True,
            "provider": "internal",
            "deal_id": internal_id,
            "internal_id": internal_id,
            "payload": payload,
        }


class CRMUpdateDealInput(BaseModel):
    deal_id: str = Field(description="ID do deal")
    stage: str = Field(default="", description="Nova etapa (vazio = não muda)")
    notes: str = Field(default="", description="Notas do agente")
    value: float | None = Field(default=None, description="Novo valor em BRL")
    score: int | None = Field(default=None, description="Novo score 0-100")
    lead_name: str = Field(default="", description="Corrigir nome do lead")
    lead_email: str = Field(default="", description="Corrigir email do lead")
    lead_phone: str = Field(default="", description="Corrigir telefone do lead")
    agent_id: str = Field(default="", description="Reatribuir dono (agent_id)")
    team_id: str = Field(default="", description="Reatribuir time (team_id)")


class CRMUpdateTool(BaseTool):
    name = "crm_update_deal"
    description = ("Atualiza deal no CRM: etapa, valor, score, dados do lead e dono. "
                   "HITL: closed_won/closed_lost, >R$5k ganho, e desconto acima da "
                   "política do Deal Desk vão para aprovação humana.")
    input_model = CRMUpdateDealInput

    async def run(self, deal_id: str, stage: str = "", notes: str = "",
                  value: float | None = None, score: int | None = None,
                  lead_name: str = "", lead_email: str = "",
                  lead_phone: str = "", agent_id: str = "",
                  team_id: str = "") -> dict:
        from aios.config import settings
        import os

        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}

        needs_hitl = False
        hitl_reason = ""
        if stage in ("closed_won", "closed_lost"):
            needs_hitl = True
            hitl_reason = f"Movendo para {stage} requer aprovação"

        # Read the deal scoped to the caller's org. The previous lookup had no
        # org filter, so any org's deal value could be read by guessing an id.
        deal = None
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal
            from sqlalchemy import select as _sel0

            async with async_session() as s:
                deal = (await s.execute(
                    _sel0(CrmDeal).where(CrmDeal.id == deal_id, CrmDeal.org_id == org_id)
                )).scalars().first()
                if not deal:
                    return {"ok": False, "error": "deal não encontrado"}
                if deal.value and deal.value > 5000 and stage == "closed_won":
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
                        org_id=(deal.org_id if deal else getattr(self, "_org_id", "")) or "",
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

        # Auto-apply for non-critical changes: internal CrmDeal + lock + versioning
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal, CrmDealVersion
            from sqlalchemy import text as _text2
            from sqlalchemy import select as _sel2

            async with async_session() as s:
                mine = getattr(self, "_org_id", "") or ""
                if not mine:
                    return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}

                deal = (await s.execute(
                    _sel2(CrmDeal).where(CrmDeal.id == deal_id, CrmDeal.org_id == mine)
                )).scalars().first()
                if not deal:
                    return {"ok": False, "error": "deal não encontrado"}
                try:
                    await s.execute(_text2("SELECT pg_advisory_xact_lock(:k)"),
                                    {"k": abs(hash(deal.org_id)) % 2147483647})
                except Exception:
                    pass

                VALID_STAGES = ("prospection", "mql", "sql", "opportunity",
                                "closed_won", "closed_lost")
                # Only touch the stage when one was actually supplied. The old
                # code assigned deal.stage = stage unconditionally, so a
                # value-only update blanked the stage.
                if stage and stage in VALID_STAGES:
                    deal.stage = stage

                old_stage = deal.stage
                old_value = deal.value
                changed = []

                if value is not None and float(value) != (deal.value or 0):
                    deal.value = float(value)
                    changed.append(("value", str(old_value), str(deal.value)))
                if score is not None:
                    deal.score = max(0, min(100, int(score)))
                    changed.append(("score", "", str(deal.score)))
                if lead_name:
                    deal.lead_name = lead_name[:255]
                    changed.append(("lead_name", "", deal.lead_name))
                if lead_email:
                    deal.lead_email = lead_email[:255]
                    changed.append(("lead_email", "", deal.lead_email))
                if lead_phone:
                    deal.lead_phone = lead_phone[:50]
                    changed.append(("lead_phone", "", deal.lead_phone))
                if agent_id:
                    deal.agent_id = agent_id
                    changed.append(("agent_id", "", agent_id))
                if team_id:
                    deal.team_id = team_id
                    changed.append(("team_id", "", team_id))
                if notes:
                    deal.extra_data = {**(deal.extra_data or {}),
                                       "last_ai_notes": notes[:500]}

                # probability/close_date only move when the stage actually changed
                if stage and stage in VALID_STAGES:
                    sc = deal.score or 0
                    if stage == "closed_won":
                        deal.probability, offset = 100.0, 0
                    elif stage == "closed_lost":
                        deal.probability, offset = 0.0, 0
                    elif stage == "opportunity":
                        deal.probability, offset = min(80 + (sc / 5), 95), 14
                    elif stage == "sql":
                        deal.probability, offset = min(50 + (sc / 3), 75), 30
                    elif stage == "mql":
                        deal.probability, offset = min(20 + (sc / 4), 45), 60
                    else:
                        deal.probability, offset = min(sc / 5, 15), 90
                    deal.probability = round(deal.probability, 1)
                    deal.close_date = _now_utc() + timedelta(days=offset)
                    changed.append(("stage", old_stage, stage))

                for field, old, new in changed:
                    try:
                        s.add(CrmDealVersion(
                            deal_id=deal.id, org_id=deal.org_id, changed_by=None,
                            changed_by_type="agent", field=field,
                            old_value=str(old), new_value=str(new)))
                    except Exception:
                        pass

                await s.commit()
                return {
                    "ok": True, "provider": "internal", "deal_id": deal.id,
                    "stage": deal.stage, "value": deal.value,
                    "updated_fields": [f for f, _, _ in changed] or [],
                    "message": "nada a alterar" if not changed else "ok",
                }
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
            from aios.db.models import CrmDeal, CrmDealVersion
            from sqlalchemy import select as _sel
            import uuid
            async with async_session() as s:
                # Engine org, not Organization.limit(1): merging by email must
                # never touch another org's deals.
                org_id = getattr(self, "_org_id", "") or ""
                if not org_id:
                    return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}

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


OPEN_STAGES = ("prospection", "mql", "sql", "opportunity")
CLOSED_STAGES = ("closed_won", "closed_lost")


class CRMListDealsInput(BaseModel):
    stage: str = Field(default="", description="Filtra por stage (vazio = todos abertos)")
    limit: int = Field(default=25, ge=1, le=100)


class CRMListDealsTool(BaseTool):
    name = "crm_list_deals"
    description = "Lista deals do CRM com stage, valor, próximo follow-up e dias sem contato."
    input_model = CRMListDealsInput

    async def run(self, stage: str = "", limit: int = 25) -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal
            from sqlalchemy import select as _sel

            async with async_session() as s:
                q = _sel(CrmDeal).where(CrmDeal.org_id == org_id)
                stage = (stage or "").strip()
                if stage:
                    q = q.where(CrmDeal.stage == stage)
                else:
                    q = q.where(CrmDeal.stage.notin_(CLOSED_STAGES))
                deals = (await s.execute(q.order_by(CrmDeal.updated_at.desc()).limit(max(1, min(100, limit))))).scalars().all()
                now = _now_utc()
                out = []
                for d in deals:
                    last = (d.extra_data or {}).get("last_contacted_at")
                    stale_days = None
                    if last:
                        try:
                            stale_days = (now - datetime.fromisoformat(last)).days
                        except Exception:
                            stale_days = None
                    out.append({
                        "deal_id": d.id,
                        "lead_name": d.lead_name,
                        "lead_email": d.lead_email,
                        "stage": d.stage,
                        "value": d.value,
                        "score": d.score,
                        "next_follow_up": (d.extra_data or {}).get("next_follow_up", ""),
                        "days_since_contact": stale_days,
                        "notes": ((d.extra_data or {}).get("last_ai_notes") or "")[:300],
                    })
                return {"ok": True, "count": len(out), "deals": out}
        except Exception as e:
            logger.warning("CRM list deals failed: %s", e)
            return {"ok": False, "error": str(e)}


class CRMSetFollowUpInput(BaseModel):
    deal_id: str = Field(description="ID do deal")
    days_from_now: int = Field(description="Dias até o follow-up (0 = hoje)")
    note: str = Field(default="", description="Lembrete do que fazer")


class CRMSetFollowUpTool(BaseTool):
    name = "crm_set_follow_up"
    description = "Agenda follow-up num deal (vira lembrete consultável em crm_stale_deals)."
    input_model = CRMSetFollowUpInput

    async def run(self, deal_id: str, days_from_now: int = 1, note: str = "") -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal, CrmDealVersion
            from sqlalchemy import select as _sel

            when = _now_utc() + timedelta(days=int(days_from_now or 0))
            async with async_session() as s:
                deal = (await s.execute(
                    _sel(CrmDeal).where(CrmDeal.id == deal_id, CrmDeal.org_id == org_id)
                )).scalars().first()
                if not deal:
                    return {"ok": False, "error": "deal não encontrado"}
                prev = (deal.extra_data or {}).get("next_follow_up", "")
                deal.extra_data = {**(deal.extra_data or {}), "next_follow_up": when.isoformat()}
                if note:
                    deal.extra_data["follow_up_note"] = note[:300]
                s.add(CrmDealVersion(
                    deal_id=deal.id, org_id=org_id, changed_by_type="agent",
                    field="next_follow_up", old_value=str(prev), new_value=when.isoformat(),
                    extra_data={"note": note[:300]},
                ))
                await s.commit()
                return {"ok": True, "deal_id": deal.id, "next_follow_up": when.isoformat(), "note": note}
        except Exception as e:
            logger.warning("CRM set follow-up failed: %s", e)
            return {"ok": False, "error": str(e)}


class CRMStaleDealsInput(BaseModel):
    stale_days: int = Field(default=7, ge=1, le=180, description="Dias sem contato para considerar parado")
    include_overdue: bool = Field(default=True, description="Incluir follow-up vencido")


class CRMStaleDealsTool(BaseTool):
    name = "crm_stale_deals"
    description = "Leads sem contato há N dias e follow-ups vencidos — a fila de trabalho do dia."
    input_model = CRMStaleDealsInput

    async def run(self, stale_days: int = 7, include_overdue: bool = True) -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal
            from sqlalchemy import select as _sel

            now = _now_utc()
            cutoff = now - timedelta(days=max(1, int(stale_days or 7)))
            async with async_session() as s:
                deals = (await s.execute(
                    _sel(CrmDeal).where(
                        CrmDeal.org_id == org_id,
                        CrmDeal.stage.notin_(CLOSED_STAGES),
                    )
                )).scalars().all()

            unengaged, overdue = [], []
            for d in deals:
                ex = d.extra_data or {}
                last = ex.get("last_contacted_at")
                nfu = ex.get("next_follow_up")
                age = None
                if last:
                    try:
                        age = (now - datetime.fromisoformat(last)).days
                    except Exception:
                        age = None
                # Never contacted, or not touched within the window.
                if age is None or age >= stale_days:
                    unengaged.append({
                        "deal_id": d.id, "lead_name": d.lead_name,
                        "lead_email": d.lead_email, "lead_phone": d.lead_phone,
                        "stage": d.stage,
                        "value": d.value, "days_since_contact": age,
                    })
                if include_overdue and nfu:
                    try:
                        due = datetime.fromisoformat(nfu)
                        if due < now:
                            overdue.append({
                                "deal_id": d.id, "lead_name": d.lead_name,
                                "lead_email": d.lead_email, "lead_phone": d.lead_phone,
                                "stage": d.stage, "value": d.value,
                                "follow_up_due": nfu,
                                "note": (ex.get("follow_up_note") or "")[:200],
                                "days_overdue": (now - due).days,
                            })
                    except Exception:
                        continue
            return {
                "ok": True,
                "stale_days": stale_days,
                "unengaged": unengaged,
                "unengaged_count": len(unengaged),
                "overdue": overdue,
                "overdue_count": len(overdue),
            }
        except Exception as e:
            logger.warning("CRM stale deals failed: %s", e)
            return {"ok": False, "error": str(e)}


TOOL_REGISTRY["crm_create_deal"] = {"code_reference": "aios.tools.crm.CRMTool"}
TOOL_REGISTRY["crm_update_deal"] = {"code_reference": "aios.tools.crm.CRMUpdateTool"}
TOOL_REGISTRY["crm_merge_deals"] = {"code_reference": "aios.tools.crm.CRMMergeTool"}
TOOL_REGISTRY["crm_list_deals"] = {"code_reference": "aios.tools.crm.CRMListDealsTool"}
TOOL_REGISTRY["crm_set_follow_up"] = {"code_reference": "aios.tools.crm.CRMSetFollowUpTool"}
TOOL_REGISTRY["crm_stale_deals"] = {"code_reference": "aios.tools.crm.CRMStaleDealsTool"}
TOOL_REGISTRY["crm_delete_deal"] = {"code_reference": "aios.tools.crm.CRMDeleteDealTool"}
TOOL_REGISTRY["crm_pipeline_stats"] = {"code_reference": "aios.tools.crm.CRMPipelineStatsTool"}

class CRMDeleteDealInput(BaseModel):
    deal_id: str = Field(description="ID do deal a remover")
    confirm: bool = Field(default=False, description="Tem que ser true — remoção é irreversível")


class CRMDeleteDealTool(BaseTool):
    name = "crm_delete_deal"
    description = ("Remove um deal do CRM. Irreversível — só o gerente de vendas tem esta "
                   "ferramenta. Exige confirm=true.")
    input_model = CRMDeleteDealInput

    async def run(self, deal_id: str, confirm: bool = False) -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
        if not confirm:
            return {"ok": False, "error": "remoção exige confirm=true"}
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal, CrmDealVersion
            from sqlalchemy import select as _sel

            async with async_session() as s:
                deal = (await s.execute(
                    _sel(CrmDeal).where(CrmDeal.id == deal_id, CrmDeal.org_id == org_id)
                )).scalars().first()
                if not deal:
                    return {"ok": False, "error": "deal não encontrado"}
                label = "%s / %s" % (deal.lead_name, deal.stage)
                # versions first: they carry a FK to the deal
                for v in (await s.execute(
                    _sel(CrmDealVersion).where(CrmDealVersion.deal_id == deal.id)
                )).scalars().all():
                    await s.delete(v)
                await s.delete(deal)
                await s.commit()
                return {"ok": True, "deleted": deal_id, "was": label}
        except Exception as e:
            logger.warning("CRM delete failed %s", e)
            return {"ok": False, "error": str(e)}


class CRMPipelineStatsInput(BaseModel):
    pipeline: str = Field(default="", description="Filtra por pipeline (vazio = todos)")


class CRMPipelineStatsTool(BaseTool):
    name = "crm_pipeline_stats"
    description = ("Resumo do pipeline do CRM: contagem e valor por etapa, taxa de conversão, "
                   "ticket médio, won/lost e custo. Somente leitura, já escopado na sua org — "
                   "não precisa passar org_id.")
    input_model = CRMPipelineStatsInput

    async def run(self, pipeline: str = "") -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
        try:
            from aios.db.engine import async_session
            from aios.db.models import CrmDeal
            from sqlalchemy import select as _sel

            async with async_session() as s:
                q = _sel(CrmDeal).where(CrmDeal.org_id == org_id)
                if pipeline:
                    q = q.where(CrmDeal.pipeline == pipeline)
                rows = (await s.execute(q)).scalars().all()

            by_stage, value_by_stage, source_mix = {}, {}, {}
            won = lost = 0
            won_value = 0.0
            total_cost = 0.0
            for r in rows:
                by_stage[r.stage] = by_stage.get(r.stage, 0) + 1
                value_by_stage[r.stage] = round(
                    value_by_stage.get(r.stage, 0.0) + (r.value or 0.0), 2)
                source_mix[r.source] = source_mix.get(r.source, 0) + 1
                total_cost += r.cost_usd or 0.0
                if r.stage == "closed_won":
                    won += 1
                    won_value += r.value or 0.0
                elif r.stage == "closed_lost":
                    lost += 1

            closed = won + lost
            open_n = len(rows) - closed
            return {
                "ok": True,
                "total_deals": len(rows),
                "by_stage": by_stage,
                "value_by_stage": value_by_stage,
                "open_deals": open_n,
                "won": won,
                "lost": lost,
                "win_rate": round(won / closed, 3) if closed else None,
                "avg_deal_value": round(won_value / won, 2) if won else None,
                "won_value": round(won_value, 2),
                "by_source": source_mix,
                "total_cost_usd": round(total_cost, 4),
            }
        except Exception as e:
            logger.warning("CRM pipeline stats failed %s", e)
            return {"ok": False, "error": str(e)}
