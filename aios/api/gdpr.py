from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Agent, Organization

router = APIRouter(prefix="/api/org", tags=["gdpr"])


@router.delete("")
async def delete_org(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    if user.role not in ("admin", "org_admin", "superadmin"):
        raise HTTPException(403)
    org = await db.get(Organization, org_id)
    if not org or org.slug in ("pixor", "default"):
        raise HTTPException(400, detail="org protegida")
    # Erasure used to delete five tables by hand. Postgres enforces foreign
    # keys and the schema declares no ON DELETE CASCADE, so deleting Agent or
    # Team raised IntegrityError on the ~24 and ~7 tables that reference them --
    # the endpoint could only ever 500. Worse, 30+ tables holding PII, call
    # transcripts and encrypted third-party tokens were never deleted at all,
    # which is the opposite of what a GDPR/LGPD erasure is for.
    #
    # Walk the whole org subgraph instead: collect the org's row ids from every
    # table that carries org_id, then transitively delete tables that reference
    # those rows through a foreign key, children before parents so FK order is
    # always satisfied.
    from aios.db.models import Base
    from sqlalchemy import or_ as _or_  # noqa: F401

    tables = list(Base.metadata.sorted_tables)
    def pk_name(t):
        return list(t.primary_key.columns)[0].name

    # seed: every table with an org_id column
    pending: dict = {}
    for tbl in tables:
        if "org_id" in tbl.c:
            rows = (await db.execute(select(pk_name(tbl)).where(tbl.c.org_id == org_id))).all()
            if rows:
                pending[tbl] = {r[0] for r in rows}

    # transitively include child tables that have no org_id of their own
    while True:
        grew = False
        for tbl in tables:
            if tbl in pending:
                continue
            for fk in tbl.foreign_keys:
                parent = fk.column.table
                if parent in pending:
                    vals = list(pending[parent])[:900]
                    if not vals:
                        break
                    rows = (await db.execute(select(pk_name(tbl)).where(fk.column.in_(vals)))).all()
                    if rows:
                        pending[tbl] = {r[0] for r in rows}
                        grew = True
                    break
        if not grew:
            break

    # delete children first (sorted_tables is parents-first, so reverse it)
    for tbl in reversed(tables):
        ids = pending.get(tbl)
        if not ids:
            continue
        vals = list(ids)
        for i in range(0, len(vals), 900):  # stay under the bind-param limit
            chunk = vals[i:i + 900]
            await db.execute(delete(tbl).where(pk_name(tbl).in_(chunk)))

    await db.delete(org)
    await db.commit()
    return {"ok": True, "deleted": org_id, "tables_cleared": len(pending)}


@router.get("/export")
async def export_org(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    from aios.db.models import ChannelConnection, Conversation, CrmDeal, Message

    org = await db.get(Organization, org_id)
    if not org:
        from fastapi import HTTPException

        raise HTTPException(404, "organization not found")
    agents = (
        (await db.execute(select(Agent).where(Agent.org_id == org_id))).scalars().all()
    )
    # LGPD Art. 18: the subject gets their personal data, not just the org's
    # roster. Conversations, message contents and lead records are where the
    # personal data lives; an export of names alone does not satisfy it.
    # Secrets are never exported: channel configs carry tokens and credentials.
    conversations = (
        await db.execute(select(Conversation).where(Conversation.org_id == org_id))
    ).scalars().all()
    conv_ids = [c.id for c in conversations]
    messages: list = []
    truncated = False
    if conv_ids:
        messages = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id.in_(conv_ids))
                .order_by(Message.created_at.desc())
                .limit(10001)
            )
        ).scalars().all()
        if len(messages) > 10000:
            messages = messages[:10000]
            truncated = True
    deals = (
        await db.execute(select(CrmDeal).where(CrmDeal.org_id == org_id))
    ).scalars().all()
    channels = (
        await db.execute(select(ChannelConnection).where(ChannelConnection.org_id == org_id))
    ).scalars().all()
    return {
        "org": {"id": org.id, "name": org.name, "slug": org.slug},
        "agents": [{"id": a.id, "name": a.name} for a in agents],
        "conversations": [
            {
                "id": c.id,
                "channel": c.channel,
                "external_id": c.external_id,
                "contact": (c.extra_data or {}).get("contact_name")
                or (c.extra_data or {}).get("contact_phone"),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in conversations
        ],
        "messages": [
            {
                "id": m.id,
                "conversation_id": m.conversation_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "messages_truncated": truncated,
        "crm_deals": [
            {
                "id": d.id,
                "lead_name": d.lead_name,
                "lead_email": d.lead_email,
                "lead_phone": d.lead_phone,
                "stage": d.stage,
                "value": d.value,
            }
            for d in deals
        ],
        "channels": [
            {"id": c.id, "channel_type": c.channel_type, "label": c.label}
            for c in channels
        ],
    }
