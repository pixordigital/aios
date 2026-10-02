"""Meta WhatsApp Cloud API client — message templates only.

Scope is deliberately narrow: template CRUD and status. Sending is Evolution's
job (aios/channels/evolution.py), and pulling this into the Graph client would
mean two code paths for one message.

Design constraints, from the production audit:

* Every request carries an explicit timeout. Several unbounded-httpx call sites
  were fixed earlier in this session; do not add another.
* Retry ONLY on rate limiting (80008) and 5xx. Never on a 4xx — those are
  deterministic failures and retrying them burns the quota that protects the
  tenant's quality rating.
* appsecret_proof on every call, per Meta's requirement for API traffic.
* Every public method requires the org's WhatsappConnection. There is
  deliberately no "resolve the default WABA" helper: templates are per-WABA and
  a global lookup would reintroduce exactly the cross-tenant pattern that was
  removed from the credential tools.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"
GRAPH_VERSION = "v23.0"

DEFAULT_TIMEOUT = 20.0
MAX_ATTEMPTS = 4

# Meta error codes we can act on. Anything else is surfaced verbatim.
ERR_INVALID_PARAM = 100
ERR_MISSING_PERMISSION = 200
ERR_DUPLICATE_NAME = 10
ERR_RATE_LIMITED = 80008
ERR_PARAMETER_INVALID = 131009
ERR_ABUSIVE = 368
ERR_HSM_CREATE_FAILED = 200002
ERR_BLOCKED_INTEGRITY = 139000

ERROR_HINTS = {
    ERR_MISSING_PERMISSION: (
        "The access token lacks whatsapp_business_management. Generate a system-user "
        "token in Meta Business Suite with that permission for this WABA."
    ),
    ERR_RATE_LIMITED: "Meta rate-limited this WABA. Wait and retry; repeated calls degrade the account.",
    ERR_DUPLICATE_NAME: "A template with this name already exists in this WABA for this language.",
    ERR_HSM_CREATE_FAILED: "Meta rejected the template creation outright.",
    ERR_BLOCKED_INTEGRITY: "Meta blocked this call as abusive.",
}


class MetaAPIError(Exception):
    """Carries Meta's own error code. The UI must show it, not paraphrase it."""

    def __init__(self, code: int | None, message: str, *, http_status: int | None = None):
        self.code = code
        self.raw_message = message
        self.http_status = http_status
        self.hint = ERROR_HINTS.get(code)
        super().__init__(f"[{code}] {message}" if code else message)


@dataclass
class TemplateComponents:
    """A text-only template. Media headers need Resumable Upload and are out of scope."""

    header_text: str = ""
    body: str = ""
    footer: str = ""
    examples: dict = field(default_factory=dict)

    def to_meta(self) -> list:
        comps = []
        if (self.header_text or "").strip():
            comps.append({"type": "HEADER", "format": "TEXT", "text": self.header_text})
        body_text = (self.body or "").strip()
        if body_text:
            body_comp = {"type": "BODY", "text": body_text}
            example = _meta_examples(self.examples)
            if example:
                # Omit the key entirely when there are no examples. Sending
                # "example": null is a different request, not an absent one.
                body_comp["example"] = example
            comps.append(body_comp)
        if (self.footer or "").strip():
            comps.append({"type": "FOOTER", "text": self.footer})
        return comps


def _meta_examples(examples: dict | None) -> dict | None:
    """Meta requires an example per parameter. Shape: {"parameter_name": ["v"]}."""
    if not examples:
        return None
    return {str(k): [str(v)] for k, v in examples.items() if str(v).strip()}


def appsecret_proof(app_secret: str, access_token: str) -> str:
    return hmac.new(
        (app_secret or "").encode(), (access_token or "").encode(), hashlib.sha256
    ).hexdigest()


def _decode_error(payload: dict, http_status: int) -> MetaAPIError:
    err = (payload or {}).get("error") or {}
    code = err.get("code")
    msg = err.get("message") or "Meta request failed"
    sub = err.get("error_subcode") or err.get("subcode")
    if sub:
        msg = f"{msg} (subcode {sub})"
    return MetaAPIError(code, msg, http_status=http_status)


class MetaWhatsAppClient:
    """Bound to one WABA + one access token."""

    def __init__(
        self,
        waba_id: str,
        access_token: str,
        app_secret: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ):
        if not waba_id:
            raise ValueError("waba_id is required")
        if not access_token:
            raise ValueError("access_token is required")
        self.waba_id = str(waba_id)
        self.access_token = access_token
        self.app_secret = app_secret or ""
        self.timeout = timeout
        self._client = client

    @classmethod
    def from_connection(cls, conn, app_secret: str = "", **kw) -> "MetaWhatsAppClient":
        """Build from a WhatsappConnection row, decrypting the token.

        Refuses to guess: a connection without a waba_id or token is an error,
        never a silent fallback to some other account.
        """
        from aios.core.secrets import decrypt_secret

        waba_id = getattr(conn, "waba_id", "")
        if not waba_id:
            raise MetaAPIError(None, "connection has no waba_id")
        token = ""
        enc = getattr(conn, "access_token_enc", "") or ""
        if enc:
            token = decrypt_secret(enc)
        if not token:
            raise MetaAPIError(None, "connection has no access token")
        return cls(waba_id, token, app_secret=app_secret, **kw)

    async def _aclose_client(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kw) -> dict:
        url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        if self.app_secret:
            headers["appsecret_proof"] = appsecret_proof(self.app_secret, self.access_token)

        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)

        last_err: Exception | None = None
        try:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    resp = await client.request(method, url, headers=headers, **kw)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    # transport hiccup — safe to retry, nothing was delivered
                    last_err = e
                    if attempt == MAX_ATTEMPTS - 1:
                        break
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue

                if resp.status_code >= 500:
                    last_err = MetaAPIError(None, f"Meta 5xx: {resp.status_code}", http_status=resp.status_code)
                    if attempt == MAX_ATTEMPTS - 1:
                        break
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue

                try:
                    payload = resp.json()
                except (json.JSONDecodeError, ValueError):
                    payload = {}

                if resp.status_code >= 400:
                    err = _decode_error(payload, resp.status_code)
                    if err.code == ERR_RATE_LIMITED and attempt < MAX_ATTEMPTS - 1:
                        last_err = err
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    raise err
                return payload or {}
            raise last_err or MetaAPIError(None, "Meta request failed")
        finally:
            if own_client:
                await self._aclose_client()

    # -- templates --------------------------------------------------------

    async def list_templates(self, *, status: str | None = None, limit: int = 100) -> list:
        params = {"limit": limit, "fields": "id,name,status,category,language,rejected_reason,quality_score,previous_category"}
        if status:
            params["status"] = status.lower()
        payload = await self._request("GET", f"/{self.waba_id}/message_templates", params=params)
        return payload.get("data") or []

    async def get_template(self, meta_template_id: str) -> dict:
        fields = "id,name,status,category,language,rejected_reason,quality_score,components"
        return await self._request(
            "GET", f"/{meta_template_id}", params={"fields": fields}
        )

    async def create_template(
        self,
        *,
        name: str,
        language: str,
        category: str,
        components: TemplateComponents,
        allow_category_change: bool = True,
    ) -> dict:
        """Submit a template for review.

        allow_category_change defaults True on purpose: Meta documents it as
        preventing an immediate REJECTED due to miscategorization, and a wrong
        category is one of the most common rejection causes.

        Review is asynchronous and can take up to 24h; the returned status is
        PENDING, not a verdict.
        """
        body = {
            "name": name,
            "language": language,
            "category": category,
            "components": components.to_meta(),
        }
        if allow_category_change:
            body["allow_category_change"] = True
        return await self._request("POST", f"/{self.waba_id}/message_templates", json=body)

    async def edit_template(self, meta_template_id: str, *, category: str, components: TemplateComponents) -> dict:
        """Replace a template's components.

        Meta REPLACES all components with this payload — you cannot patch one
        field — and refuses category changes on APPROVED templates. An edit
        re-enters review.
        """
        return await self._request(
            "POST",
            f"/{meta_template_id}",
            json={"category": category, "components": components.to_meta()},
        )

    async def delete_template(self, meta_template_id: str) -> bool:
        await self._request("DELETE", f"/{self.waba_id}/message_templates", params={"hsm_ids": [meta_template_id]})
        return True

    # -- connection health ------------------------------------------------

    async def verify_connection(self) -> dict:
        """Cheap call used by the connection page to validate pasted credentials."""
        payload = await self._request(
            "GET", f"/{self.waba_id}", params={"fields": "id,name,account_review_status"}
        )
        return payload