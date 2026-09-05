import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Workflow, WorkflowRun, Credential
from aios.core.secrets import encrypt_secret, decrypt_secret
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/automations", tags=["automations"])

AUTOMATION_TEMPLATES = {
    "webhook_to_slack": {
        "name": "Webhook → Slack",
        "description": "Recebe webhook e notifica no Slack",
        "icon": "💬",
        "trigger": {"type": "webhook", "name": "Entrada webhook"},
        "nodes": [
            {"label": "Notificar Slack", "tool_name": "http_request", "tool_args": {"url": "https://hooks.slack.com/services/SEU/WEBHOOK", "method": "POST", "body": {"text": "Novo evento: {{json.body}}"}}, "output_key": "slack"},
        ],
    },
    "cron_report": {
        "name": "Agendamento → Relatório",
        "description": "Todo dia coleta dados e envia e-mail",
        "icon": "⏰",
        "trigger": {"type": "cron", "cron": "0 9 * * *", "name": "Diário 9h"},
        "nodes": [
            {"label": "Buscar dados", "tool_name": "http_request", "tool_args": {"url": "https://api.example.com/data", "method": "GET"}, "output_key": "data"},
            {"label": "Gerar resumo", "tool_name": "code", "tool_args": {"code": "output = {'resumo': f\"Registros: {len(input_data.get('json', [])) if isinstance(input_data.get('json'), list) else 1}\"}"}, "depends_on": ["__prev__"], "output_key": "resumo"},
        ],
    },
    "lead_to_crm": {
        "name": "Lead → CRM",
        "description": "Webhook de lead cria deal no CRM",
        "icon": "🎯",
        "trigger": {"type": "webhook", "name": "Novo lead"},
        "nodes": [
            {"label": "Criar deal", "tool_name": "http_request", "tool_args": {"url": "{{json.crm_url}}", "method": "POST", "body": {"name": "{{json.json.name}}", "email": "{{json.json.email}}"}}, "output_key": "crm"},
        ],
    },
    "enrich_and_notify": {
        "name": "Enriquecer + Notificar",
        "description": "Busca API, transforma e chama agente IA",
        "icon": "🤖",
        "trigger": {"type": "webhook", "name": "Enriquecer"},
        "nodes": [
            {"label": "Enriquecer", "tool_name": "http_request", "tool_args": {"url": "https://api.example.com/enrich?email={{json.json.email}}", "method": "GET"}, "output_key": "enrich"},
            {"label": "Formatar", "tool_name": "transform", "tool_args": {"input": {"raw": "{{outputs.enrich}}"}, "mapping": {"mensagem": "Lead {{json.json.name}} enriquecido"}}, "depends_on": ["__prev__"], "output_key": "msg"},
        ],
    },
    "poll_and_branch": {
        "name": "Condicional",
        "description": "Roteia fluxo por condição (idade, valor, status)",
        "icon": "🔀",
        "trigger": {"type": "webhook", "name": "Evento condicional"},
        "nodes": [
            {"label": "Verificar condição", "tool_name": "if_branch", "tool_args": {"condition": "input.get('valor',0) > 100", "input": {"valor": "{{json.json.valor}}"}}, "output_key": "check"},
            {"label": "Ação premium", "tool_name": "http_request", "tool_args": {"url": "https://hooks.example.com/premium", "method": "POST", "body": {"msg": "premium"}}, "depends_on": ["__prev__"], "condition": "outputs['check'] and 'true' in outputs['check']", "output_key": "premium"},
        ],
    },
    "delayed_action": {
        "name": "Atraso + Ação",
        "description": "Espera N segundos e executa próxima etapa",
        "icon": "⏳",
        "trigger": {"type": "webhook", "name": "Com atraso"},
        "nodes": [
            {"label": "Aguardar 10s", "tool_name": "wait", "tool_args": {"seconds": 10}, "output_key": "wait"},
            {"label": "Executar", "tool_name": "http_request", "tool_args": {"url": "https://example.com/done", "method": "POST", "body": {"done": True}}, "depends_on": ["__prev__"], "output_key": "done"},
        ],
    },
}

def _require_role(user, allowed: list[str]):
    if user.role not in allowed and user.role != "superadmin":
        raise HTTPException(403, f"role {user.role} not allowed, need {allowed}")

# --- Triggers ---

@router.get("/workflows/{wf_id}/triggers")
async def list_triggers(wf_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.db.models import AutomationTrigger
    wf = await db.get(Workflow, wf_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404, "workflow not found")
    res = await db.execute(select(AutomationTrigger).where(AutomationTrigger.workflow_id == wf_id))
    return res.scalars().all()

@router.post("/workflows/{wf_id}/triggers")
async def create_trigger(wf_id: str, body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    _require_role(user, ["admin","org_admin"])
    from aios.db.models import AutomationTrigger
    wf = await db.get(Workflow, wf_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404, "workflow not found")
    ttype = body.get("type")
    if ttype not in ("webhook","cron","event","manual","schedule"):
        raise HTTPException(400, "type must be webhook|cron|event|manual|schedule")
    if ttype == "schedule":
        ttype = "cron"
    cfg = body.get("config") or {}
    cron_expr = body.get("cron") or body.get("cron_expr") or cfg.get("cron")
    event_type = body.get("event_type") or cfg.get("event")
    webhook_path = None
    if ttype == "webhook":
        webhook_path = body.get("webhook_path") or f"wh_{uuid.uuid4().hex[:16]}"
        # ensure unique
        existing = (await db.execute(select(AutomationTrigger).where(AutomationTrigger.webhook_path==webhook_path))).scalars().first()
        if existing:
            webhook_path = f"wh_{uuid.uuid4().hex[:16]}"
    trig = AutomationTrigger(
        workflow_id=wf_id, org_id=org_id, type=ttype, name=body.get("name",""),
        config=cfg, webhook_path=webhook_path, cron_expr=cron_expr, event_type=event_type,
        is_active=body.get("is_active", True)
    )
    if cron_expr and ttype=="cron":
        try:
            from croniter import croniter
            if not croniter.is_valid(cron_expr):
                raise HTTPException(400, f"invalid cron: {cron_expr}")
            base = datetime.now(timezone.utc)
            nxt = croniter(cron_expr, base).get_next(datetime)
            trig.next_run_at = nxt
        except ImportError:
            pass
    db.add(trig)
    await db.commit()
    await db.refresh(trig)
    return trig

@router.delete("/workflows/{wf_id}/triggers/{trig_id}")
async def delete_trigger(wf_id: str, trig_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.db.models import AutomationTrigger
    trig = await db.get(AutomationTrigger, trig_id)
    if not trig or trig.workflow_id != wf_id or trig.org_id != org_id:
        raise HTTPException(404)
    await db.delete(trig)
    await db.commit()
    return {"ok": True}

@router.patch("/workflows/{wf_id}/triggers/{trig_id}")
async def update_trigger(wf_id: str, trig_id: str, body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.db.models import AutomationTrigger
    trig = await db.get(AutomationTrigger, trig_id)
    if not trig or trig.workflow_id != wf_id or trig.org_id != org_id:
        raise HTTPException(404)
    for k in ("name","is_active","config","cron_expr","event_type"):
        if k in body:
            setattr(trig, k, body[k])
    if "cron" in body:
        trig.cron_expr = body["cron"]
    if trig.cron_expr and trig.type=="cron":
        try:
            from croniter import croniter
            base = datetime.now(timezone.utc)
            trig.next_run_at = croniter(trig.cron_expr, base).get_next(datetime)
        except Exception:
            pass
    await db.commit()
    await db.refresh(trig)
    return trig

# --- Webhook dispatcher (public) ---
@router.api_route("/webhook/{path}", methods=["GET","POST","PUT","DELETE","PATCH"])
async def webhook_dispatch(path: str, request: Request):
    from aios.db.engine import async_session
    from aios.db.models import AutomationTrigger, Workflow
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    async with async_session() as sess:
        trig = (await sess.execute(select(AutomationTrigger).where(AutomationTrigger.webhook_path==path, AutomationTrigger.is_active==True))).scalars().first()
        if not trig:
            raise HTTPException(404, "webhook not found")
        wf = await sess.get(Workflow, trig.workflow_id, options=[selectinload(Workflow.nodes)])
        if not wf:
            raise HTTPException(404, "workflow not found")
        try:
            body = await request.body()
            j = None
            try:
                j = await request.json()
            except Exception:
                j = None
            headers = dict(request.headers)
            query = dict(request.query_params)
        except Exception:
            body, j, headers, query = b"", None, {}, {}
        payload = {"webhook_path": path, "method": request.method, "headers": headers, "query": query, "body": body.decode()[:5000] if body else "", "json": j}
        # enqueue workflow run
        from aios.db.models import WorkflowRun
        run = WorkflowRun(workflow_id=wf.id, org_id=trig.org_id, status="pending", inputs={"input": json.dumps(payload)[:8000], "webhook": payload, "trigger_id": trig.id}, conversation_id=None)
        sess.add(run)
        await sess.commit()
        await sess.refresh(run)
        try:
            from aios.tasks.queue import enqueue_job
            await enqueue_job("aios.tasks.jobs.workflow_run_job", {"workflow_id": wf.id, "run_id": run.id})
            run.status = "running"
            await sess.commit()
        except Exception:
            from aios.core.workflow import WorkflowDef, WorkflowNode as WNode, WorkflowEngine
            wdef = WorkflowDef(id=wf.id, name=wf.name, timeout=wf.timeout_seconds, entry_node=wf.entry_node_id)
            for n in wf.nodes:
                wdef.nodes[n.id] = WNode(id=n.id, agent_id=n.agent_id, tool_name=n.tool_name, tool_args=n.tool_args or {}, depends_on=n.depends_on or [], condition=n.condition, output_key=n.output_key, timeout=n.timeout_seconds)
            eng = WorkflowEngine()
            res = await eng.run(wdef, run.id, json.dumps(payload))
            run.status = "done" if res.ok() else "failed"
            run.outputs = res.outputs
            run.node_status = res.node_status
            await sess.commit()
        return {"ok": True, "run_id": run.id, "workflow_id": wf.id}

# --- Credentials ---

@router.get("/credentials")
async def list_credentials(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    res = await db.execute(select(Credential).where(Credential.org_id==org_id))
    items = res.scalars().all()
    return [{"id": c.id, "name": c.name, "cred_type": c.cred_type, "extra_data": c.extra_data, "created_at": str(c.created_at)} for c in items]

@router.post("/credentials")
async def create_credential(body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    _require_role(user, ["admin","org_admin"])
    name = body.get("name")
    ctype = body.get("cred_type") or body.get("type")
    data = body.get("data") or body.get("value") or {}
    if not name or not ctype:
        raise HTTPException(400, "name and cred_type required")
    if not isinstance(data, dict):
        data = {"value": str(data)}
    enc = encrypt_secret(json.dumps(data))
    cred = Credential(org_id=org_id, name=name, cred_type=ctype, data_enc=enc, extra_data=body.get("extra_data") or {})
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return {"id": cred.id, "name": cred.name, "cred_type": cred.cred_type}

@router.delete("/credentials/{cred_id}")
async def delete_credential(cred_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    cred = await db.get(Credential, cred_id)
    if not cred or cred.org_id != org_id:
        raise HTTPException(404)
    await db.delete(cred)
    await db.commit()
    return {"ok": True}

@router.get("/executions")
async def list_executions(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), limit: int = 20):
    from aios.db.models import WorkflowRun
    res = await db.execute(select(WorkflowRun).where(WorkflowRun.org_id==org_id).order_by(WorkflowRun.created_at.desc()).limit(limit))
    return res.scalars().all()

@router.get("/templates")
async def list_templates():
    return [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "nodes"}} | {"node_count": len(v.get("nodes",[]))} for k, v in AUTOMATION_TEMPLATES.items()]

@router.post("/templates/{tpl_id}/create")
async def create_from_template(tpl_id: str, body: dict = {}, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    _require_role(user, ["admin","org_admin"])
    from aios.db.models import AutomationTrigger, WorkflowNode
    tpl = AUTOMATION_TEMPLATES.get(tpl_id)
    if not tpl:
        raise HTTPException(404, "template not found")
    name = body.get("name") or tpl["name"]
    wf = Workflow(org_id=org_id, name=name, description=tpl["description"], timeout_seconds=120)
    db.add(wf)
    await db.flush()
    prev_id = None
    for nd in tpl.get("nodes", []):
        deps = []
        if nd.get("depends_on") == ["__prev__"] and prev_id:
            deps = [prev_id]
        elif nd.get("depends_on"):
            deps = [d for d in nd["depends_on"] if d != "__prev__"]
        node = WorkflowNode(workflow_id=wf.id, label=nd.get("label",""), tool_name=nd.get("tool_name"), tool_args=nd.get("tool_args",{}), depends_on=deps, condition=nd.get("condition"), output_key=nd.get("output_key","result"))
        db.add(node)
        await db.flush()
        prev_id = node.id
    trig_cfg = dict(tpl.get("trigger", {}))
    ttype = trig_cfg.pop("type", "webhook")
    if ttype == "webhook":
        trig = AutomationTrigger(workflow_id=wf.id, org_id=org_id, type="webhook", name=trig_cfg.get("name",""), config=trig_cfg, webhook_path=f"wh_{uuid.uuid4().hex[:16]}", is_active=True)
        db.add(trig)
    elif ttype == "cron":
        cron_expr = trig_cfg.get("cron", "0 9 * * *")
        trig = AutomationTrigger(workflow_id=wf.id, org_id=org_id, type="cron", name=trig_cfg.get("name",""), config=trig_cfg, cron_expr=cron_expr, is_active=True)
        try:
            from croniter import croniter
            trig.next_run_at = croniter(cron_expr, datetime.now(timezone.utc)).get_next(datetime)
        except Exception:
            pass
        db.add(trig)
    await db.commit()
    await db.refresh(wf)
    return {"id": wf.id, "name": wf.name, "template": tpl_id}

# --- Event trigger helper (internal) ---
async def fire_event_triggers(event_type: str, org_id: str, payload: dict):
    from aios.db.engine import async_session
    from aios.db.models import AutomationTrigger, Workflow
    from sqlalchemy.orm import selectinload
    async with async_session() as sess:
        trigs = (await sess.execute(select(AutomationTrigger).where(AutomationTrigger.org_id==org_id, AutomationTrigger.type=="event", AutomationTrigger.event_type==event_type, AutomationTrigger.is_active==True))).scalars().all()
        for trig in trigs:
            wf = await sess.get(Workflow, trig.workflow_id, options=[selectinload(Workflow.nodes)])
            if not wf:
                continue
            from aios.db.models import WorkflowRun
            run = WorkflowRun(workflow_id=wf.id, org_id=org_id, status="pending", inputs={"input": json.dumps(payload)[:8000], "event": payload, "trigger_id": trig.id})
            sess.add(run)
            await sess.commit()
            await sess.refresh(run)
            try:
                from aios.tasks.queue import enqueue_job
                await enqueue_job("aios.tasks.jobs.workflow_run_job", {"workflow_id": wf.id, "run_id": run.id})
            except Exception:
                pass
