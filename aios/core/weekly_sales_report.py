"""Evidence based weekly sales report, PDF rendering, and SMTP delivery."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from io import BytesIO
import logging
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from sqlalchemy import func, select

logger = logging.getLogger(__name__)
TZ_NAME = "America/Sao_Paulo"


def completed_week(today: date | None = None) -> tuple[datetime, datetime]:
    """Previous completed Monday-to-Monday week in the report timezone."""
    from zoneinfo import ZoneInfo
    today = today or datetime.now(ZoneInfo(TZ_NAME)).date()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(days=7)
    zone = ZoneInfo(TZ_NAME)
    return tuple(datetime.combine(day, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
                 for day in (start, monday))


def _recommendations(payload: dict) -> list[dict]:
    out = []
    goal = payload.get("goal") or {}
    if goal.get("target_brl"):
        pct = goal.get("pct", 0)
        if pct < 50:
            out.append({"title": "Revise o ritmo da meta", "evidence": f"A meta mensal está em {pct:.1f}% ({goal.get('won_brl', 0):.2f} de {goal['target_brl']:.2f} BRL).", "action": "Revise a meta e combine uma ação comercial para esta semana.", "target_url": "/dashboard/crm#goals"})
    missing = payload.get("unattributed_count", 0)
    if missing:
        out.append({"title": "Complete a atribuição dos negócios", "evidence": f"{missing} negócio(s) ativos não têm agente responsável identificado.", "action": "Atribua um responsável para permitir acompanhamento por agente.", "target_url": "/dashboard/crm"})
    return out[:3]


async def collect_week(db, org_id: str, start: datetime, end: datetime) -> dict:
    from aios.core.sales_goals import month_progress
    from aios.db.models import Agent, CrmDeal, CrmDealVersion, SalesGoal
    previous_start, previous_end = start - (end - start), start

    async def metrics(a, b):
        rows = (await db.execute(select(CrmDeal.stage, func.count(CrmDeal.id), func.coalesce(func.sum(CrmDeal.value), 0))
            .where(CrmDeal.org_id == org_id, CrmDeal.updated_at >= a, CrmDeal.updated_at < b)
            .group_by(CrmDeal.stage))).all()
        return {stage: {"count": count, "value_brl": round(float(value or 0), 2)} for stage, count, value in rows}

    current, previous = await metrics(start, end), await metrics(previous_start, previous_end)
    stage_changes = (await db.execute(select(CrmDealVersion.old_value, CrmDealVersion.new_value, func.count(CrmDealVersion.id))
        .where(CrmDealVersion.org_id == org_id, CrmDealVersion.field == "stage", CrmDealVersion.created_at >= start, CrmDealVersion.created_at < end)
        .group_by(CrmDealVersion.old_value, CrmDealVersion.new_value))).all()
    agent_rows = (await db.execute(select(Agent.name, func.count(CrmDeal.id), func.coalesce(func.sum(CrmDeal.value), 0))
        .join(CrmDeal, CrmDeal.agent_id == Agent.id).where(CrmDeal.org_id == org_id, Agent.org_id == org_id,
        CrmDeal.stage == "closed_won",
        ((CrmDeal.close_date.is_not(None)) & (CrmDeal.close_date >= start) & (CrmDeal.close_date < end)) |
        ((CrmDeal.close_date.is_(None)) & (CrmDeal.updated_at >= start) & (CrmDeal.updated_at < end))
        ).group_by(Agent.name))).all()
    active = (await db.execute(select(func.count(CrmDeal.id)).where(CrmDeal.org_id == org_id,
        CrmDeal.stage.notin_(["closed_won", "closed_lost"]), CrmDeal.agent_id.is_(None)))).scalar() or 0
    progress = await month_progress(db, org_id)
    target = (await db.execute(select(SalesGoal).where(SalesGoal.org_id == org_id,
        SalesGoal.year_month == progress["year_month"], SalesGoal.team_id.is_(None)))).scalar_one_or_none()
    progress["target_brl"] = float(target.target_brl) if target else 0.0
    return {"week_start": start.date().isoformat(), "week_end": (end - timedelta(days=1)).date().isoformat(),
        "current": current, "previous": previous,
        "stage_changes": [{"from": a or "(vazio)", "to": b or "(vazio)", "count": n} for a, b, n in stage_changes],
        "agents": [{"name": n, "deal_count": c, "value_brl": round(float(v or 0), 2)} for n, c, v in agent_rows],
        "unattributed_count": int(active), "goal": progress}


def render_pdf(report: dict, recommendations: list[dict], review_url: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Relatório semanal de vendas AIOS")
    styles = getSampleStyleSheet(); story = [Paragraph("Relatório semanal de vendas", styles["Title"]),
        Paragraph(f"Semana de {report['week_start']} a {report['week_end']}", styles["Normal"]), Spacer(1, 12)]
    for section, title in (("current", "Semana do relatório"), ("previous", "Semana anterior")):
        story.append(Paragraph(title + " — negócios atualizados, por etapa atual", styles["Heading2"]))
        values = report.get(section, {})
        story.append(Paragraph("; ".join(f"{escape(str(stage))}: {data['count']} negócio(s), R$ {data['value_brl']:.2f}" for stage, data in values.items()) or "Sem negócios registrados nesta semana.", styles["BodyText"]))
    goal = report.get("goal", {})
    story.extend([Paragraph("Meta mensal", styles["Heading2"]), Paragraph(
        f"{goal.get('pct', 0):.1f}% — R$ {goal.get('won_brl', 0):.2f} de R$ {goal.get('target_brl', 0):.2f}." if goal.get("target_brl") else "Nenhuma meta mensal cadastrada.", styles["BodyText"]),
        Paragraph("Responsáveis identificados", styles["Heading2"])])
    story.append(Paragraph("; ".join(f"{escape(str(a['name']))}: {a['deal_count']} negócio(s), R$ {a['value_brl']:.2f}" for a in report.get("agents", [])) or "Sem atribuição confiável por agente.", styles["BodyText"]))
    story.append(Paragraph(f"{report.get('unattributed_count', 0)} negócio(s) ativos sem agente responsável registrado.", styles["BodyText"]))
    story.append(Paragraph("Mudanças de etapa", styles["Heading2"]))
    story.append(Paragraph("; ".join(f"{escape(str(m['from']))} → {escape(str(m['to']))}: {m['count']}" for m in report.get("stage_changes", [])) or "Nenhuma mudança registrada.", styles["BodyText"]))
    if report.get("follow_up"):
        story.append(Paragraph("Acompanhamento da semana anterior", styles["Heading2"]))
        for item in report["follow_up"]:
            if item.get("tried") is None:
                status = "Ainda sem revisão; informe se tentou e o que aconteceu no AIOS."
            elif item.get("tried"):
                status = f"Tentada; resultado informado: {escape(item.get('outcome') or 'sem resultado registrado')}"
            else:
                status = "Não tentada."
            story.append(Paragraph(f"{escape(item['title'])}: {status}", styles["BodyText"]))
    story.append(Paragraph("Sugestões", styles["Heading2"]))
    for item in recommendations:
        base = urlsplit(review_url)
        target = item.get("target_url") or "/dashboard/crm"
        target_url = f"{base.scheme}://{base.netloc}{target}" if base.scheme and base.netloc else review_url
        story.append(Paragraph(f"<b>{escape(item['title'])}</b><br/>{escape(item['evidence'])}<br/>Próximo passo: {escape(item['action'])}<br/><link href='{escape(target_url)}' color='blue'>Abrir tela relacionada no AIOS</link>", styles["BodyText"]))
        story.append(Spacer(1, 8))
    story.append(Paragraph(f"Revisar sugestões: <link href='{review_url}' color='blue'>{review_url}</link>", styles["BodyText"]))
    doc.build(story)
    return buf.getvalue()


async def send_pdf(org_id: str, to: str, subject: str, pdf: bytes, review_url: str) -> bool:
    from aios.core.org_settings import get_org_secret_async
    from aios.config import settings
    host = await get_org_secret_async(org_id, "smtp_host") or settings.smtp_host
    user = await get_org_secret_async(org_id, "smtp_user") or settings.smtp_user
    password = await get_org_secret_async(org_id, "smtp_password") or settings.smtp_password
    port = await get_org_secret_async(org_id, "smtp_port") or "587"
    sender = await get_org_secret_async(org_id, "smtp_from_email") or user
    if not host or not sender or not to:
        return False
    msg = EmailMessage(); msg["Subject"] = subject; msg["From"] = sender; msg["To"] = to
    msg.set_content(f"Seu relatório semanal de vendas está anexado. Revise as sugestões: {review_url}")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="relatorio-semanal-vendas.pdf")
    try:
        import aiosmtplib
        await aiosmtplib.send(msg, hostname=host, port=int(port), start_tls=int(port) == 587,
                              username=user or None, password=password or None)
        return True
    except Exception:
        logger.exception("weekly sales report email failed for org %s", org_id)
        return False


async def smtp_configured(org_id: str) -> bool:
    from aios.core.org_settings import get_org_secret_async
    from aios.config import settings
    host = await get_org_secret_async(org_id, "smtp_host") or settings.smtp_host
    sender = await get_org_secret_async(org_id, "smtp_from_email") or await get_org_secret_async(org_id, "smtp_user") or settings.smtp_user
    return bool(host and sender)
