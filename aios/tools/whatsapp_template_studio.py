"""Agent-facing tools for WhatsApp template authoring.

Deliberately no submit tool. Submitting consumes WABA review quota and rejections
degrade the tenant's quality rating, so that action stays behind a human click in
the dashboard. An agent can draft, lint and read; it cannot reach Meta.

Every tool scopes by `self._org_id`, which ToolEngine sets from the running
agent's org (aios/core/tools.py). Templates are per-WABA, so the WABA is also
resolved from the caller's own connection — never a global default.
"""

import logging

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


async def _connection(org_id: str):
    """The caller's own WABA connection, or None."""
    if not org_id:
        return None
    from sqlalchemy import select
    from aios.db.backend import db_session
    from aios.db.models import WhatsappConnection

    async with db_session() as db:
        return (await db.execute(
            select(WhatsappConnection).where(WhatsappConnection.org_id == org_id)
            .order_by(WhatsappConnection.created_at.desc())
        )).scalars().first()


async def _existing_bodies(org_id: str, language: str, exclude_id: str = ""):
    from sqlalchemy import select
    from aios.db.backend import db_session
    from aios.db.models import WhatsappTemplate

    q = select(WhatsappTemplate.body).where(
        WhatsappTemplate.org_id == org_id, WhatsappTemplate.language == language
    )
    if exclude_id:
        q = q.where(WhatsappTemplate.id != exclude_id)
    async with db_session() as db:
        return [b for b in (await db.execute(q)).scalars().all() if b]


class WhatsappTemplateListInput(BaseModel):
    status: str = Field(default="", description="Filter by status, ex: REJECTED, APPROVED, PAUSED")


class WhatsappTemplateList(BaseTool):
    name = "whatsapp_template_list"
    description = (
        "List this org's WhatsApp message templates with their Meta review status. "
        "Use to find templates that were rejected, paused or disabled before drafting new ones."
    )
    input_model = WhatsappTemplateListInput

    async def run(self, status: str = "") -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {"error": "sem org no contexto"}
        from sqlalchemy import select
        from aios.db.backend import db_session
        from aios.db.models import WhatsappTemplate

        async with db_session() as db:
            q = select(WhatsappTemplate).where(WhatsappTemplate.org_id == org_id)
            if status:
                q = q.where(WhatsappTemplate.status == status.upper())
            rows = (await db.execute(
                q.order_by(WhatsappTemplate.updated_at.desc()).limit(100)
            )).scalars().all()
        return {
            "templates": [
                {
                    "id": t.id, "name": t.name, "language": t.language,
                    "category": t.category, "status": t.status,
                    # Meta's own enum, or null when it told us nothing.
                    "rejected_reason": t.rejected_reason,
                    "rejection_note": t.rejection_note,
                    "sendable": t.status == "APPROVED",
                    "body": t.body,
                }
                for t in rows
            ],
            "count": len(rows),
        }


class WhatsappTemplateLintInput(BaseModel):
    name: str = Field(default="", description="Template name: lowercase letters, digits, underscore")
    language: str = Field(default="pt_BR")
    category: str = Field(default="UTILITY", description="UTILITY | MARKETING | AUTHENTICATION")
    header_text: str = Field(default="", description="Optional header, no formatting")
    body: str = Field(default="", description="Body text with sequential {{1}}, {{2}} variables")
    footer: str = Field(default="", description="Optional footer, no variables, max 60 chars")
    examples: dict = Field(default_factory=dict, description='{"1":"João","2":"12/03"}')


class WhatsappTemplateLint(BaseTool):
    name = "whatsapp_template_lint"
    description = (
        "Check a WhatsApp template draft against Meta's published rejection rules before it is "
        "submitted. Deterministic, not a guess: sequential variables, dangling/floating parameters, "
        "footer and header limits, sensitive identifiers, promotional wording in UTILITY, missing "
        "examples, and duplication against templates that already exist in this WABA."
    )
    input_model = WhatsappTemplateLintInput

    async def run(self, name: str = "", language: str = "pt_BR", category: str = "UTILITY",
                  header_text: str = "", body: str = "", footer: str = "",
                  examples: dict | None = None, **kw) -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        from aios.core.template_lint import TemplateDraft, can_submit, errors, lint_template, summarise, warnings

        existing = await _existing_bodies(org_id, language or "pt_BR") if org_id else []
        findings = lint_template(TemplateDraft(
            name=name or "", language=language or "pt_BR",
            category=(category or "UTILITY").upper(),
            header_text=header_text or "", body=body or "", footer=footer or "",
            examples=examples or {}, existing_bodies=existing,
        ))
        return {
            "can_submit": can_submit(findings),
            "errors": [f.as_dict() for f in errors(findings)],
            "warnings": [f.as_dict() for f in warnings(findings)],
            "summary": summarise(findings),
            "disclaimer": (
                "These are the rules Meta publishes. Passing them does not mean approval; "
                "Meta also reviews content and policy by human and ML judgement."
            ),
        }


class WhatsappTemplateDraftInput(BaseModel):
    name: str = Field(description="Template name: lowercase letters, digits, underscore only")
    body: str = Field(description="Body text")
    language: str = Field(default="pt_BR")
    category: str = Field(default="UTILITY", description="UTILITY | MARKETING | AUTHENTICATION")
    header_text: str = Field(default="")
    footer: str = Field(default="")
    examples: dict = Field(default_factory=dict)
    notes: str = Field(default="", description="Why this template is needed / the decision it serves")


class WhatsappTemplateDraft(BaseTool):
    name = "whatsapp_template_draft"
    description = (
        "Save a WhatsApp template as a LOCAL DRAFT for a human to review and submit. "
        "This never contacts Meta. Run whatsapp_template_lint first to catch rejection causes."
    )
    input_model = WhatsappTemplateDraftInput

    async def run(self, name: str = "", body: str = "", language: str = "pt_BR",
                  category: str = "UTILITY", header_text: str = "", footer: str = "",
                  examples: dict | None = None, notes: str = "", **kw) -> dict:
        org_id = getattr(self, "_org_id", "") or ""
        if not org_id:
            return {"error": "sem org no contexto (agente sem org_id)"}
        from sqlalchemy import select
        from aios.db.backend import db_session
        from aios.db.models import WhatsappTemplate

        conn = await _connection(org_id)
        if not conn:
            return {"error": "org sem WABA conectada; peça ao humano para conectar em /dashboard/whatsapp/templates/connect"}

        # Lint before saving so an obviously-rejected draft never sits in the queue.
        from aios.core.template_lint import TemplateDraft as TD, errors, lint_template
        existing = await _existing_bodies(org_id, language or "pt_BR")
        findings = lint_template(TD(
            name=name or "", language=language or "pt_BR",
            category=(category or "UTILITY").upper(),
            header_text=header_text or "", body=body or "", footer=footer or "",
            examples=examples or {}, existing_bodies=existing,
        ))
        blocking = errors(findings)

        async with db_session() as db:
            dupe = (await db.execute(
                select(WhatsappTemplate).where(
                    WhatsappTemplate.org_id == org_id,
                    WhatsappTemplate.waba_id == conn.waba_id,
                    WhatsappTemplate.name == name,
                    WhatsappTemplate.language == (language or "pt_BR"),
                )
            )).scalars().first()
            if dupe:
                return {
                    "ok": False,
                    "error": "ja existe um template com esse nome e idioma nesta WABA",
                    "existing_id": dupe.id,
                    "existing_status": dupe.status,
                }
            tpl = WhatsappTemplate(
                org_id=org_id, connection_id=conn.id, waba_id=conn.waba_id,
                name=name, language=language or "pt_BR",
                category=(category or "UTILITY").upper(),
                header_text=header_text or "", body=body or "", footer=footer or "",
                examples_json=examples or {}, status="DRAFT", local_notes=notes or "",
            )
            db.add(tpl)
            await db.commit()
            return {
                "ok": True,
                "draft_id": tpl.id,
                "status": "DRAFT",
                "lint_errors": [f.as_dict() for f in blocking],
                "next_step": (
                    "Rascunho salvo. Um humano precisa revisar em "
                    "/dashboard/whatsapp/templates e clicar em enviar ao Meta."
                ),
            }


TOOL_REGISTRY["whatsapp_template_list"] = {
    "code_reference": "aios.tools.whatsapp_template_studio.WhatsappTemplateList",
}
TOOL_REGISTRY["whatsapp_template_lint"] = {
    "code_reference": "aios.tools.whatsapp_template_studio.WhatsappTemplateLint",
}
TOOL_REGISTRY["whatsapp_template_draft"] = {
    "code_reference": "aios.tools.whatsapp_template_studio.WhatsappTemplateDraft",
}