import logging
import httpx

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY
from aios.config import settings

logger = logging.getLogger(__name__)


class WhatsAppTemplateTool(BaseTool):
    name = "whatsapp_template"
    description = "Send WhatsApp template message via Evolution API (for outside 24h window, avoids 131047). Use when text send fails with 131047."
    parameters = {
        "type": "object",
        "properties": {
            "number": {"type": "string", "description": "WhatsApp number with country code, ex: 5511999999999"},
            "template": {"type": "string", "description": "Template name, ex: aios_reengajamento_1"},
            "language": {"type": "string", "description": "Language code, ex: pt_BR", "default": "pt_BR"},
            "params": {"type": "array", "items": {"type": "string"}, "description": "Template body params [nome, empresa, assunto]"},
            "instance": {"type": "string", "description": "Evolution instance name (optional, uses default)"},
        },
        "required": ["number", "template"],
    }

    async def run(self, number: str, template: str = "aios_reengajamento_1", language: str = "pt_BR", params: list = None, instance: str = "") -> dict:
        params = params or []
        # Build Evolution API payload for template
        # Evolution expects: number, text, template params via components
        base_url = (settings.evolution_server_url or "http://evolution:8080").rstrip("/")
        api_key = settings.evolution_api_key or "evolution_secret_change_me"
        # Try to find instance from channel or use provided
        if not instance:
            # fallback to env or first part of number
            instance = "default"

        url = f"{base_url}/message/sendTemplate/{instance}"
        # For Evolution v2.3.7, template sending is via /message/sendWhatsApp with type template
        # Try both endpoints
        payload = {
            "number": number.replace("+", "").replace("@s.whatsapp.net", ""),
            "template": template,
            "language": language,
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in params[:3]]
                }
            ] if params else []
        }
        headers = {"apikey": api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Try template endpoint first
                for endpoint in [f"{base_url}/message/sendTemplate/{instance}", f"{base_url}/message/sendWhatsApp/{instance}"]:
                    try:
                        r = await client.post(endpoint, headers=headers, json={
                            "number": payload["number"],
                            "template": template,
                            "language": language,
                            "components": payload["components"]
                        } if "Template" in endpoint else {
                            "number": payload["number"],
                            "options": {
                                "delay": 1200,
                                "presence": "composing"
                            },
                            "textMessage": {"text": f"Template {template} fallback text"}
                        })
                        if r.status_code in (200, 201):
                            return {"ok": True, "endpoint": endpoint, "response": r.json()}
                    except Exception:
                        continue
                # Fallback: try direct Evolution sendTemplate
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code in (200, 201):
                    return {"ok": True, "response": r.json()}
                return {"ok": False, "error": f"Evolution template send failed {r.status_code}: {r.text[:500]}"}
        except Exception as e:
            logger.exception("WhatsApp template send failed")
            return {"ok": False, "error": str(e)}


TOOL_REGISTRY["whatsapp_template"] = {
    "code_reference": "aios.tools.whatsapp_template.WhatsAppTemplateTool",
}
