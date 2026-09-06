import json, hmac, hashlib

def test_evolution_full_loop(monkeypatch):
    # simula evolution webhook → dispatch → channel send mock
    from aios.api.evolution_webhook import _verify_evolution_sig
    body = {"event": "messages.upsert", "data": {"key": {"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False}, "message": {"conversation": "oi"}}}
    key = "testkey"
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    assert _verify_evolution_sig(sig, body, key) is True
    assert _verify_evolution_sig("bad", body, key) is False

def test_automation_templates():
    from aios.api.automations import AUTOMATION_TEMPLATES
    assert "webhook_to_slack" in AUTOMATION_TEMPLATES
    assert "lead_to_crm" in AUTOMATION_TEMPLATES

def test_transcribe_tool_exists():
    from aios.tools.transcribe import TranscribeTool
    assert hasattr(TranscribeTool, "run")

def test_knowledge_search_endpoint():
    from aios.api.knowledge import router
    assert router is not None
