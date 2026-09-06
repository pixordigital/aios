from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

class RDStationInput(BaseModel):
    action: str = Field(description="create_lead|update_lead")
    email: str = Field(default="")
    name: str = Field(default="")
    properties: dict = Field(default_factory=dict)
    credential_id: str = Field(default="")
    api_key: str = Field(default="")

class RDStationTool(BaseTool):
    name = "rdstation"
    description = "RD Station — criar/atualizar leads"
    input_model = RDStationInput
    async def run(self, action: str, email: str = "", name: str = "", properties: dict | None = None, credential_id: str = "", api_key: str = "") -> dict:
        import httpx, json
        from aios.db.engine import async_session
        from aios.db.models import Credential
        from aios.core.secrets import decrypt_secret
        token = api_key
        if credential_id:
            try:
                async with async_session() as sess:
                    c = await sess.get(Credential, credential_id)
                    if c and c.data_enc:
                        d = json.loads(decrypt_secret(c.data_enc))
                        token = d.get("token") or d.get("value") or token
            except Exception:
                pass
        if not token:
            return {"error": "RD Station token ausente"}
        headers = {"Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            payload = {"email": email, "name": name, "cf_custom": properties or {}, "api_key": token}
            # RD legacy endpoint
            r = await client.post(f"https://api.rd.services/platform/conversions", headers=headers, json=payload) if action=="create_lead" else await client.patch(f"https://api.rd.services/platform/contacts/email:{email}", headers=headers, json=payload)
            # fallback to events API
            if r.status_code >= 400:
                r2 = await client.post("https://api.rd.services/platform/events", headers=headers, json={"event_type":"CONVERSION","event_family":"CDP","payload":{"email":email,"conversion_identifier": name or "lead","cf_custom": properties or {}}})
                return {"status": r2.status_code, "body": r2.text[:4000], "ok": r2.status_code in (200,201)}
            return {"status": r.status_code, "body": r.text[:4000], "ok": r.status_code in (200,201)}

TOOL_REGISTRY["rdstation"] = {"code_reference": "aios.tools.rdstation.RDStationTool"}
