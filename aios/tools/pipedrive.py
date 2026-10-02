from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY
class PipedriveInput(BaseModel):
    action: str = Field(description="create_person|create_deal|create_activity")
    name: str = Field(default="")
    email: str = Field(default="")
    value: float = Field(default=0)
    properties: dict = Field(default_factory=dict)
    credential_id: str = Field(default="")
    api_token: str = Field(default="")

class PipedriveTool(BaseTool):
    name = "pipedrive"
    description = "Pipedrive CRM — pessoas, deals, atividades"
    input_model = PipedriveInput
    async def run(self, action: str, name: str = "", email: str = "", value: float = 0, properties: dict | None = None, credential_id: str = "", api_token: str = "") -> dict:
        import httpx, json
        from aios.db.engine import async_session
        from aios.db.models import Credential
        from aios.core.secrets import decrypt_secret
        token = api_token
        domain = (properties or {}).pop("domain", "api.pipedrive.com")
        if credential_id:
            try:
                async with async_session() as sess:
                    c = await sess.get(Credential, credential_id)
                    if c and c.data_enc:
                        d = json.loads(decrypt_secret(c.data_enc))
                        token = d.get("token") or d.get("value") or token
                        domain = d.get("domain", domain)
            except Exception:
                pass
        if not token:
            return {"error": "Pipedrive token ausente"}
        base = f"https://{domain}/v1"
        async with httpx.AsyncClient(timeout=20) as client:
            if action == "create_person":
                r = await client.post(f"{base}/persons", params={"api_token": token}, json={"name": name, "email": email, **(properties or {})})
                return {"status": r.status_code, "body": r.text[:4000], "ok": r.status_code in (200,201)}
            elif action == "create_deal":
                r = await client.post(f"{base}/deals", params={"api_token": token}, json={"title": name or email, "value": value, **(properties or {})})
                return {"status": r.status_code, "body": r.text[:4000], "ok": r.status_code in (200,201)}
            elif action == "create_activity":
                r = await client.post(f"{base}/activities", params={"api_token": token}, json={"subject": name, "type": "call", **(properties or {})})
                return {"status": r.status_code, "body": r.text[:4000]}
            return {"error": f"action {action} inválida"}

TOOL_REGISTRY["pipedrive"] = {"code_reference": "aios.tools.pipedrive.PipedriveTool"}
