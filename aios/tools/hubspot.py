from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

class HubSpotInput(BaseModel):
    action: str = Field(description="create_contact|create_deal|search_contact")
    email: str = Field(default="")
    name: str = Field(default="")
    properties: dict = Field(default_factory=dict)
    credential_id: str = Field(default="", description="Credential id com Bearer HubSpot")
    api_key: str = Field(default="")

class HubSpotTool(BaseTool):
    name = "hubspot"
    description = "HubSpot CRM — criar/buscar contatos e deals"
    input_model = HubSpotInput
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
            return {"error": "HubSpot token ausente (credential_id ou api_key)"}
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            if action in ("create_contact","create"):
                payload = {"properties": {"email": email, "firstname": name, **(properties or {})}}
                r = await client.post("https://api.hubapi.com/crm/v3/objects/contacts", headers=headers, json=payload)
                return {"status": r.status_code, "body": r.text[:4000], "ok": r.status_code in (200,201)}
            elif action == "search_contact":
                r = await client.post("https://api.hubapi.com/crm/v3/objects/contacts/search", headers=headers, json={"filterGroups":[{"filters":[{"propertyName":"email","operator":"EQ","value":email}]}]})
                return {"status": r.status_code, "body": r.text[:4000]}
            elif action == "create_deal":
                payload = {"properties": {"dealname": name or email, "dealstage": "appointmentscheduled", **(properties or {})}}
                r = await client.post("https://api.hubapi.com/crm/v3/objects/deals", headers=headers, json=payload)
                return {"status": r.status_code, "body": r.text[:4000], "ok": r.status_code in (200,201)}
            return {"error": f"action desconhecida {action}"}

TOOL_REGISTRY["hubspot"] = {"code_reference": "aios.tools.hubspot.HubSpotTool"}
