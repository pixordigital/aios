"""Lead research tools — the prospector writes, the sales manager reviews.

Leads live in `crm_deals` with `source="lead_finder"` and stage `prospection`,
so the existing kanban, export and SDR handoff keep working without a second
store. The research-only fields (ICP, website, evidence) live in `extra_data`;
`lead_status` is the review state the dashboard and the manager filter on.
"""

import logging
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

LEAD_SOURCE = "lead_finder"
LEAD_STATUSES = ("new", "approved", "rejected", "sent_to_sdr")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _out(d) -> dict:
    ex = d.extra_data or {}
    return {
        "lead_id": d.id,
        "name": d.lead_name,
        "email": d.lead_email,
        "phone": d.lead_phone,
        "company": ex.get("company", ""),
        "website": ex.get("website", ""),
        "industry": ex.get("industry", ""),
        "location": ex.get("location", ""),
        "company_size": ex.get("company_size", ""),
        "fit_score": d.score,
        "status": ex.get("lead_status", "new"),
        "icp": ex.get("icp", ""),
        "batch": ex.get("batch", ""),
        "source_url": ex.get("source_url", ""),
        "notes": ex.get("notes", ""),
        "stage": d.stage,
        "assigned_agent_id": d.agent_id,
    }


def _org(tool) -> str:
    return getattr(tool, "_org_id", "") or ""


async def _load(org_id: str):
    from aios.db.engine import async_session
    from aios.db.models import CrmDeal

    async with async_session() as s:
        rows = (
            await s.execute(
                select(CrmDeal)
                .where(CrmDeal.org_id == org_id, CrmDeal.source == LEAD_SOURCE)
                .order_by(CrmDeal.created_at.desc())
                .limit(2000)
            )
        ).scalars().all()
    return rows


def _matches(d, q="", status="", batch="", industry="", min_score=0) -> bool:
    ex = d.extra_data or {}
    if status and ex.get("lead_status", "new") != status:
        return False
    if batch and ex.get("batch", "") != batch:
        return False
    if industry and industry.lower() not in (ex.get("industry", "") or "").lower():
        return False
    if (d.score or 0) < min_score:
        return False
    if q:
        hay = " ".join(str(v) for v in (
            d.lead_name, d.lead_email, d.lead_phone, ex.get("company", ""),
            ex.get("website", ""), ex.get("location", ""),
        )).lower()
        if q.lower() not in hay:
            return False
    return True


class LeadSaveInput(BaseModel):
    name: str = Field(description="Nome da empresa ou do contato (obrigatório)")
    email: str = Field(default="", description="Email público de contato")
    phone: str = Field(default="", description="Telefone público, com DDI")
    company: str = Field(default="", description="Empresa, se o nome for da pessoa")
    role: str = Field(default="", description="Cargo do contato, se pessoa")
    website: str = Field(default="", description="Site oficial")
    industry: str = Field(default="", description="Setor/nicho")
    location: str = Field(default="", description="Cidade/UF/país")
    company_size: str = Field(default="", description="1-10|11-50|51-200|200+")
    fit_score: int = Field(default=0, ge=0, le=100, description="Aderência ao ICP, 0-100")
    icp: str = Field(description="Perfil de cliente ideal que originou esta busca")
    batch: str = Field(default="", description="Nome do lote/busca (default: o ICP)")
    source_url: str = Field(default="", description="URL pública onde os dados foram encontrados")
    notes: str = Field(default="", description="Evidência curta: por que este lead adere ao ICP")


class LeadSaveTool(BaseTool):
    name = "lead_save"
    description = (
        "Salva um lead pesquisado no CRM (etapa prospecção, fonte lead_finder). "
        "Deduplica por email ou nome+site. Use uma vez por lead."
    )
    input_model = LeadSaveInput

    async def run(
        self,
        name: str,
        icp: str,
        email: str = "",
        phone: str = "",
        company: str = "",
        role: str = "",
        website: str = "",
        industry: str = "",
        location: str = "",
        company_size: str = "",
        fit_score: int = 0,
        batch: str = "",
        source_url: str = "",
        notes: str = "",
    ) -> dict:
        org_id = _org(self)
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "name é obrigatório"}
        if not (email or phone or website):
            return {"ok": False, "error": "informe ao menos email, telefone ou site"}
        if not (icp or "").strip():
            return {"ok": False, "error": "icp é obrigatório"}

        from aios.db.engine import async_session
        from aios.db.models import CrmDeal

        email_l = (email or "").strip().lower()
        website_l = (website or "").strip().lower().rstrip("/")
        # shortcut: dedupe compares the org's leads in Python; switch to a
        # unique index on (org_id, lower(email)) / (org_id, website, name) past ~10k leads.
        async with async_session() as s:
            existing = (
                await s.execute(
                    select(CrmDeal).where(
                        CrmDeal.org_id == org_id, CrmDeal.source == LEAD_SOURCE
                    )
                )
            ).scalars().all()
            for d in existing:
                ex = d.extra_data or {}
                same_email = bool(email_l) and (d.lead_email or "").lower() == email_l
                same_site = (
                    bool(website_l)
                    and (ex.get("website", "") or "").lower().rstrip("/") == website_l
                    and (d.lead_name or "").lower() == name.lower()
                )
                if same_email or same_site:
                    return {"ok": True, "duplicate": True, "lead": _out(d)}

            d = CrmDeal(
                org_id=org_id,
                lead_name=name,
                lead_email=(email or "").strip(),
                lead_phone=(phone or "").strip(),
                stage="prospection",
                score=max(0, min(100, int(fit_score or 0))),
                source=LEAD_SOURCE,
                agent_id=getattr(self, "_agent_id", "") or None,
                extra_data={
                    "company": company,
                    "role": role,
                    "website": website,
                    "industry": industry,
                    "location": location,
                    "company_size": company_size,
                    "icp": icp.strip(),
                    "batch": (batch or icp).strip(),
                    "source_url": source_url,
                    "notes": notes,
                    "lead_status": "new",
                    "found_at": _now().isoformat(),
                    "found_by_agent_id": getattr(self, "_agent_id", "") or "",
                },
            )
            s.add(d)
            await s.commit()
            await s.refresh(d)
        return {"ok": True, "duplicate": False, "lead": _out(d)}


class LeadListInput(BaseModel):
    q: str = Field(default="", description="Busca em nome, email, telefone, empresa, site")
    status: str = Field(default="", description="new|approved|rejected|sent_to_sdr (vazio = todos)")
    batch: str = Field(default="", description="Filtra por lote/busca")
    industry: str = Field(default="", description="Filtra por setor")
    min_score: int = Field(default=0, ge=0, le=100, description="Score mínimo de aderência")
    limit: int = Field(default=50, ge=1, le=200)


class LeadListTool(BaseTool):
    name = "lead_list"
    description = "Lista leads pesquisados com filtros — usado pelo gerente de vendas para revisar o lote."
    input_model = LeadListInput

    async def run(
        self,
        q: str = "",
        status: str = "",
        batch: str = "",
        industry: str = "",
        min_score: int = 0,
        limit: int = 50,
    ) -> dict:
        org_id = _org(self)
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
        rows = await _load(org_id)
        out = [
            _out(d) for d in rows
            if _matches(d, q=q, status=status, batch=batch,
                        industry=industry, min_score=min_score)
        ][:limit]
        return {"ok": True, "count": len(out), "leads": out}


class LeadReviewInput(BaseModel):
    lead_ids: list[str] = Field(description="IDs retornados por lead_list/lead_save")
    status: str = Field(description="approved|rejected|sent_to_sdr")
    sdr_agent_id: str = Field(default="", description="Agente SDR que assume (só em sent_to_sdr)")
    reason: str = Field(default="", description="Motivo da decisão, para a trilha")


class LeadReviewTool(BaseTool):
    name = "lead_review"
    description = (
        "Gerente de vendas aprova, rejeita ou manda um lote para o SDR. "
        "Aprovar não contata ninguém; sent_to_sdr move o lead para MQL."
    )
    input_model = LeadReviewInput

    async def run(
        self,
        lead_ids: list[str],
        status: str,
        sdr_agent_id: str = "",
        reason: str = "",
    ) -> dict:
        org_id = _org(self)
        if not org_id:
            return {"ok": False, "error": "sem org no contexto (agente sem org_id)"}
        if status not in LEAD_STATUSES:
            return {"ok": False, "error": f"status inválido: {status}"}
        ids = {i for i in (lead_ids or []) if i}
        if not ids:
            return {"ok": False, "error": "lead_ids vazio"}

        from aios.db.engine import async_session
        from aios.db.models import Agent, CrmDeal

        changed, skipped = [], []
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(CrmDeal).where(
                        CrmDeal.org_id == org_id,
                        CrmDeal.source == LEAD_SOURCE,
                        CrmDeal.id.in_(ids),
                    )
                )
            ).scalars().all()
            found = {d.id for d in rows}
            skipped = sorted(ids - found)
            if sdr_agent_id:
                sdr = await s.get(Agent, sdr_agent_id)
                if not sdr or sdr.org_id != org_id:
                    return {"ok": False, "error": "SDR não existe nesta org"}
            for d in rows:
                ex = dict(d.extra_data or {})
                ex["lead_status"] = status
                ex["reviewed_by_agent_id"] = getattr(self, "_agent_id", "") or ""
                ex["reviewed_at"] = _now().isoformat()
                if reason:
                    ex["review_reason"] = reason
                d.extra_data = ex
                if status == "sent_to_sdr":
                    d.stage = "mql"
                    if sdr_agent_id:
                        d.agent_id = sdr_agent_id
                        ex["assigned_at"] = _now().isoformat()
                changed.append(d.id)
            await s.commit()
        return {"ok": True, "changed": changed, "skipped": skipped, "status": status}


TOOL_REGISTRY["lead_save"] = {"code_reference": "aios.tools.leads.LeadSaveTool"}
TOOL_REGISTRY["lead_list"] = {"code_reference": "aios.tools.leads.LeadListTool"}
TOOL_REGISTRY["lead_review"] = {"code_reference": "aios.tools.leads.LeadReviewTool"}
