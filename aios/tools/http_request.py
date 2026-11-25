import json
import logging
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY
from aios.tools.ssrf import check_url, is_private_host

logger = logging.getLogger(__name__)

def _is_private(host: str) -> bool:
    """Compatibility wrapper around the shared, all-address SSRF check."""
    return is_private_host(host)


def _operator_allows_private(requested) -> bool:
    """Only a server-side opt-in can permit fetching internal addresses.

    Ignores any value the agent passed: the flag is only honoured when the
    operator set AIOS_ALLOW_PRIVATE_HTTP=1 in the environment.
    """
    import os
    return os.getenv("AIOS_ALLOW_PRIVATE_HTTP", "").strip().lower() in ("1", "true", "yes", "on")


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


class HttpRequestTool(BaseTool):
    name = "http_request"
    description = "Generic HTTP request (GET/POST/PUT/DELETE/PATCH) with headers/query/body/auth"
    input_model = HttpRequestInput

    async def run(self, url: str, method: str = "GET", headers: dict | None = None, query: dict | None = None, body=None, auth_type: str = "none", auth_value: str = "", auth_header: str = "Authorization", credential_id: str | None = None, timeout: int = 30, allow_private: bool | None = None) -> dict:
        # allow_private is NOT agent-settable. It used to be a tool input field,
        # which meant a prompt-injected agent could turn the SSRF guard off and
        # read cloud metadata (169.254.169.254). The operator opts in out-of-band.
        allow_private = _operator_allows_private(allow_private)
        blocked = check_url(url, allow_private=allow_private)
        if blocked:
            return {"error": blocked, "status": 0}
        method = method.upper()
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
            return {"error": f"invalid method {method}", "status": 0}
        headers = dict(headers or {})
        if credential_id:
            try:
                from aios.db.engine import async_session
                from aios.core.credential_scope import resolve_scoped_credential
                from aios.core.secrets import decrypt_secret
                async with async_session() as sess:
                    cred = await resolve_scoped_credential(
                        sess, credential_id,
                        org_id=getattr(self, "_org_id", "") or "",
                        agent_id=getattr(self, "_agent_id", "") or "",
                        tool_name=self.name,
                    )
                    if cred is None:
                        return {"error": "credential access denied", "status": 0}
                    if cred.data_enc:
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
                return {"error": "credential access denied", "status": 0}
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
                        next_url = str(httpx.URL(url_to_fetch).join(httpx.URL(nxt)))
                        blocked = check_url(next_url, allow_private=allow_private)
                        if blocked:
                            return {"error": f"redirect blocked: {blocked}", "status": 0}
                        old = urlparse(url_to_fetch)
                        new = urlparse(next_url)
                        old_origin = (old.scheme.lower(), (old.hostname or "").lower(), old.port or (443 if old.scheme == "https" else 80))
                        new_origin = (new.scheme.lower(), (new.hostname or "").lower(), new.port or (443 if new.scheme == "https" else 80))
                        if new_origin != old_origin:
                            # Auth headers, API keys, and request bodies are supplied
                            # by the caller. Never forward them to another origin.
                            return {"error": "cross-origin redirects are blocked", "status": 0}
                        url_to_fetch = next_url
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
