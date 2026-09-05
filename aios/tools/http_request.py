import ipaddress
import json
import logging
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

_PRIVATE_BLOCKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private(host: str) -> bool:
    try:
        import socket
        addr = socket.getaddrinfo(host, 80)[0][4][0]
    except Exception:
        return True
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    for block in _PRIVATE_BLOCKS:
        if ip in block:
            return True
    return False


class HttpRequestInput(BaseModel):
    url: str = Field(description="HTTPS URL")
    method: str = Field(default="GET", description="GET|POST|PUT|DELETE|PATCH|HEAD")
    headers: dict = Field(default_factory=dict)
    query: dict = Field(default_factory=dict)
    body: str | dict | None = Field(default=None, description="JSON dict or raw string")
    auth_type: str = Field(default="none", description="none|bearer|basic|api_key")
    auth_value: str = Field(default="", description="token / user:pass / key")
    auth_header: str = Field(default="Authorization", description="header for api_key")
    credential_id: str | None = Field(default=None, description="Credential id to resolve auth")
    timeout: int = Field(default=30, ge=1, le=120)
    allow_private: bool = Field(default=False)


class HttpRequestTool(BaseTool):
    name = "http_request"
    description = "Generic HTTP request (GET/POST/PUT/DELETE/PATCH) with headers/query/body/auth"
    input_model = HttpRequestInput

    async def run(self, url: str, method: str = "GET", headers: dict | None = None, query: dict | None = None, body=None, auth_type: str = "none", auth_value: str = "", auth_header: str = "Authorization", credential_id: str | None = None, timeout: int = 30, allow_private: bool = False) -> dict:
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            return {"error": "Only http/https allowed", "status": 0}
        host = parsed.hostname or ""
        if not allow_private and _is_private(host):
            return {"error": "private host blocked", "status": 0}
        method = method.upper()
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
            return {"error": f"invalid method {method}", "status": 0}
        headers = dict(headers or {})
        if credential_id:
            try:
                from aios.db.engine import async_session
                from aios.db.models import Credential
                from aios.core.secrets import decrypt_secret
                async with async_session() as sess:
                    cred = await sess.get(Credential, credential_id)
                    if cred and cred.data_enc:
                        dec = decrypt_secret(cred.data_enc)
                        cdata = json.loads(dec) if dec.startswith("{") else {"value": dec}
                        ct = cred.cred_type
                        if ct == "bearer":
                            headers["Authorization"] = f"Bearer {cdata.get('token', cdata.get('value',''))}"
                        elif ct == "api_key":
                            headers[cdata.get("header", "X-API-Key")] = cdata.get("key", cdata.get("value",""))
                        elif ct == "basic":
                            import base64
                            raw = cdata.get("value") or f"{cdata.get('username','')}:{cdata.get('password','')}"
                            headers["Authorization"] = "Basic " + base64.b64encode(raw.encode()).decode()
            except Exception as e:
                logger.warning("credential resolve failed %s: %s", credential_id, e)
        else:
            if auth_type == "bearer" and auth_value:
                headers["Authorization"] = f"Bearer {auth_value}"
            elif auth_type == "basic" and auth_value:
                import base64
                headers["Authorization"] = "Basic " + base64.b64encode(auth_value.encode()).decode()
            elif auth_type == "api_key" and auth_value:
                headers[auth_header] = auth_value
        try:
            import httpx
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                url_to_fetch = url
                for _hop in range(5):
                    kwargs: dict = {"headers": headers, "params": query or {}}
                    if body is not None and method not in ("GET", "HEAD"):
                        if isinstance(body, dict):
                            kwargs["json"] = body
                        else:
                            kwargs["content"] = str(body).encode()
                    resp = await client.request(method, url_to_fetch, **kwargs)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        nxt = resp.headers.get("location")
                        if not nxt:
                            break
                        url_to_fetch = str(httpx.URL(nxt).join(httpx.URL(url_to_fetch)))
                        parsed2 = urlparse(url_to_fetch)
                        if not allow_private and _is_private(parsed2.hostname or ""):
                            return {"error": "redirect to private blocked", "status": 0}
                        if method == "POST" and resp.status_code in (301, 302, 303):
                            method = "GET"
                        continue
                    text = resp.text[:50000]
                    try:
                        j = resp.json()
                    except Exception:
                        j = None
                    return {"status": resp.status_code, "headers": dict(resp.headers), "body": text, "json": j, "ok": 200 <= resp.status_code < 300}
                return {"error": "too many redirects", "status": 0}
        except Exception as e:
            logger.exception("http_request failed %s", url)
            return {"error": str(e), "status": 0}


TOOL_REGISTRY["http_request"] = {"code_reference": "aios.tools.http_request.HttpRequestTool"}
