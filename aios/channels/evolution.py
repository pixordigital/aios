"""Evolution API WhatsApp channel — unified Baileys + Meta Cloud API."""

import asyncio
import logging
import random
from typing import Any

import httpx

from aios.channels.base import Channel, OutboundMessage
from aios.config import settings

logger = logging.getLogger(__name__)


# ─── Outbound bubble batching ───
#
# Every send() below was one provider HTTP call = one WhatsApp bubble = one
# per-message fee, so N quick texts cost N fees. Texts to the same recipient
# arriving inside a short window are joined with a blank line and sent once.
#
# State is module-level, not on the channel: manager.build() constructs a
# fresh EvolutionChannel per send, so instance state could never accumulate a
# batch. Keyed by (instance, recipient) so tenants and conversations never mix.
# Joined by _join_texts: continuations flow with a space, separate messages
# keep the paragraph break.
#
# What never joins a batch: templates, interactive/media/audio (anything whose
# extra marks a non-text type). Those flush the pending batch first and go
# alone, preserving order. The guard, humanize delay and presence simulation
# then run once per bubble instead of once per text — fewer sends is also
# less spammy, which is what the anti-ban accounting wants.
#
# Flushes per recipient are chained: a new flush waits for the previous one,
# so bubbles always arrive in the order the texts did. Only message *content*
# is ever merged — no row is deleted and no idempotency key changes, so the
# delivery layer's retry/DLQ semantics are untouched.
#
# Crash exposure: a buffer that has not flushed yet lives only in this
# process. The window is ~2s; a crash inside it loses those texts exactly as
# a crash mid-send does today (delivery never stamped them, so the inbound
# job's retry regenerates and resends).

class _Batch:
    __slots__ = ("first", "futures", "send_one", "texts")

    def __init__(self, send_one, first):
        self.texts = [first.text or ""]
        self.futures = []
        self.send_one = send_one
        self.first = first


_buffers: dict[tuple[str, str], _Batch] = {}
_flush_tasks: dict[tuple[str, str], asyncio.Task] = {}


def _mergeable(message: OutboundMessage) -> bool:
    extra = message.extra_data or {}
    wtype = extra.get("whatsapp_type") or extra.get("type") or "text"
    return wtype == "text" and not extra.get("is_template")


def _join_texts(texts: list[str]) -> str:
    """Join burst texts into one flowing bubble.

    A bare paragraph join stacks fragments that were one sentence split
    across sends — "your number is:" / "49349" — which reads broken. So:
    a part ending in ':' flows into the next with a space (label: value),
    and a part starting lowercase continues the sentence with a space.
    Anything else (new sentence, list item, greeting) keeps the paragraph
    break — merging those would garble, not group. Whitespace-only parts
    carry no content and are dropped, unless that is all there is (a lone
    empty send behaves exactly as it does today).
    """
    parts = [t for t in (texts or []) if (t or "").strip()]
    if not parts:
        parts = texts[:1] if texts else [""]
    chunks = [parts[0]]
    for t in parts[1:]:
        prev = chunks[-1]
        if prev.rstrip().endswith(":") or t[:1].islower():
            chunks[-1] = prev.rstrip() + " " + t.lstrip()
        else:
            chunks.append(t)
    return "\n\n".join(chunks)


def _merged_message(first: OutboundMessage, texts: list[str]) -> OutboundMessage:
    return OutboundMessage(
        conversation_id=first.conversation_id,
        text=_join_texts(texts),
        channel_connection_id=first.channel_connection_id,
        extra_data=first.extra_data,
    )


def _launch_flush(key: tuple[str, str], buf: _Batch) -> asyncio.Task:
    """Send one batch, chained behind any in-flight flush for the recipient."""
    prev = _flush_tasks.get(key)

    async def _run():
        if prev is not None and not prev.done():
            await asyncio.wait({prev})
        try:
            if all(f.done() for f in buf.futures):
                # Everybody stopped waiting (cancelled jobs whose retry will
                # resend). Sending now would orphan a bubble AND duplicate it.
                logger.info("whatsapp batch %s: all waiters gone, dropping %d texts", key[1], len(buf.texts))
                return
            merged = _merged_message(buf.first, buf.texts)
            result = await buf.send_one(merged)
            logger.info(
                "whatsapp batch %s: %d texts → 1 bubble (%d chars)",
                key[1], len(buf.texts), len(merged.text),
            )
            for f in buf.futures:
                if not f.done():
                    f.set_result(result)
        except Exception:
            logger.exception("whatsapp batch %s: flush failed", key[1])
            for f in buf.futures:
                if not f.done():
                    # Delivery treats None as send failure → its retry path.
                    f.set_result(None)

    task = asyncio.ensure_future(_run())
    _flush_tasks[key] = task

    def _forget(done):
        if _flush_tasks.get(key) is done:
            del _flush_tasks[key]

    task.add_done_callback(_forget)
    return task


async def _flush_now(key: tuple[str, str]) -> None:
    """Flush the pending batch for a recipient, preserving order.

    Used when a non-mergeable message arrives (it must go after the pending
    texts) and when a batch hits its caps. Awaiting the chained task also
    covers the case where a flush is already in flight.
    """
    buf = _buffers.get(key)
    if buf is not None:
        # No await between get and del: single event loop, nothing interleaves.
        del _buffers[key]
        await _launch_flush(key, buf)
        return
    task = _flush_tasks.get(key)
    if task is not None and not task.done():
        await asyncio.wait({task})


async def _timer(key: tuple[str, str], buf: _Batch, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("whatsapp batch timer failed")
        return
    # Pop only if this exact buffer is still pending: an overflow flush may
    # have replaced it with a newer one, which owns its own timer.
    if _buffers.get(key) is buf:
        del _buffers[key]
        await _launch_flush(key, buf)


class EvolutionChannel(Channel):
    """Unified WhatsApp channel via Evolution API.

    Supports:
    - provider="baileys": WhatsApp Web (Evolution default)
    - provider="meta": Meta Cloud API (official Business API)

    Multi-tenant: one Evolution instance per client org.
    Paid plans can have multiple instances.
    """

    channel_type = "evolution"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}

    @property
    def org_id(self) -> str:
        return getattr(self.connection, "org_id", "") or ""

    @property
    def provider(self) -> str:
        """Provider mode: 'baileys' (default) or 'meta'."""
        return self._config.get("provider", "baileys")

    @property
    def instance(self) -> str:
        return self._config.get("instance", "")

    @property
    def api_key(self) -> str:
        return self._config.get("api_key", "")

    @property
    def base_url(self) -> str:
        return self._config.get("server_url", "http://evolution:8080").rstrip("/")

    async def _dispatch(self, message: OutboundMessage) -> str | None:
        if self.provider == "meta":
            return await self._send_meta(message)
        return await self._send_baileys(message)

    def _batch_key(self, message: OutboundMessage) -> tuple[str, str] | None:
        extra = message.extra_data or {}
        to = extra.get("from_number") or self._config.get("default_number", "")
        if not to:
            return None
        return (self.instance, to)

    async def send(self, message: OutboundMessage) -> str | None:
        # Unconfigured or disabled: today's direct behavior, with no pointless
        # window wait before returning None.
        if (
            not self.instance
            or not self.api_key
            or not settings.whatsapp_batch_enabled
        ):
            return await self._dispatch(message)
        key = self._batch_key(message)
        if key is None:
            return await self._dispatch(message)

        if not _mergeable(message):
            # Templates / interactive / media go alone, but after whatever is
            # already pending for this recipient — order is preserved.
            await _flush_now(key)
            return await self._dispatch(message)

        buf = _buffers.get(key)
        if buf is not None:
            current = sum(len(t) for t in buf.texts) + 2 * len(buf.texts)
            if (
                len(buf.texts) >= settings.whatsapp_batch_max_messages
                or current + len(message.text or "") + 2 > settings.whatsapp_batch_max_chars
            ):
                await _flush_now(key)
                buf = None
        if buf is None:
            # _Batch seeds texts with the first message; later ones append below.
            buf = _Batch(
                send_one=self._dispatch,
                first=message,
            )
            _buffers[key] = buf
            asyncio.ensure_future(
                _timer(key, buf, settings.whatsapp_batch_window_sec)
            )
        else:
            buf.texts.append(message.text or "")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        buf.futures.append(fut)
        return await fut

    async def _send_baileys(self, message: OutboundMessage) -> str | None:
        """Send via Baileys (WhatsApp Web)."""
        if not self.instance or not self.api_key:
            logger.warning("Evolution Baileys not configured: instance=%s", self.instance)
            return None

        if not await self._validate_url():
            return None

        to = (message.extra_data or {}).get("from_number") or self._config.get("default_number", "")
        if not to:
            logger.warning("No recipient number for Evolution Baileys send")
            return None

        from aios.core.whatsapp_guard import guard_send, humanize_delay, vary_text, record_ban_signal, persist_cooldown
        from aios.core.whatsapp.anti_ban.signals import record_event, record_response, is_quarantined

        try:
            varied = vary_text(message.text)
            if varied != message.text:
                message.text = varied
            ok, reason = await guard_send(to, message.text, provider="evolution", instance=self.instance)
            if not ok:
                logger.warning("Evolution guard block %s: %s", to, reason)
                if "global" in reason or "warmup" in reason:
                    record_ban_signal(to, 30)
                return None
            # Corroborated ban evidence (not one noisy error) blocks the whole
            # instance. The signal survives restart because it lives in the DB.
            if await is_quarantined(self.org_id, self.instance):
                logger.error(
                    "Evolution send blocked: instance %s quarantined (ban-risk critical)",
                    self.instance,
                )
                await record_event(self.org_id, self.instance, "blocked", "quarantined")
                return None
        except Exception as e:
            # Fail CLOSED. Swallowing this sent with no opt-out check, no
            # quarantine gate and no ban accounting whenever the guard or the
            # DB behind it hiccuped — the exact moment the anti-ban rules
            # exist to matter. Dropping a message is recoverable; a banned
            # number is not.
            logger.error(
                "Evolution guard raised for instance=%s to=%s; refusing to send: %s",
                self.instance, to, e,
            )
            return None

        try:
            # humanize_delay is a plain sync function. The old `await humanize_delay(...)`
            # raised TypeError on every send, and the surrounding `except Exception`
            # swallowed it into `return None` — so no Baileys message ever left the box.
            delay = humanize_delay(message.text)
            await asyncio.sleep(delay + random.uniform(0.5, 1.5))

            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    await client.post(
                        f"{self.base_url}/chat/whatsappNumbers/{self.instance}",
                        headers={"apikey": self.api_key},
                        json={"numbers": [to]},
                    )
                except Exception:
                    pass
                try:
                    await client.post(
                        f"{self.base_url}/chat/updatePresence/{self.instance}",
                        headers={"apikey": self.api_key},
                        json={"number": to, "presence": "composing"},
                    )
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                except Exception:
                    pass

                resp = await client.post(
                    f"{self.base_url}/message/sendText/{self.instance}",
                    headers={"apikey": self.api_key, "Content-Type": "application/json"},
                    json={
                        "number": to,
                        "textMessage": {"text": message.text},
                        "options": {"delay": int(delay * 1000), "presence": "composing"},
                    },
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    msg_key = data.get("key", {})
                    await record_event(self.org_id, self.instance, "sent")
                    return msg_key.get("id") or msg_key.get("remoteJid")

                # A non-2xx here is the only real evidence of a ban risk we get.
                signal = await record_response(self.org_id, self.instance, resp.status_code, resp.text[:500])
                if signal:
                    txt = resp.text[:500].lower()
                    if signal in ("ban_signal", "http_429"):
                        await persist_cooldown(self.org_id, to, 120, signal)
                    logger.warning("Evolution Baileys %s %s: %d %s", signal, to, resp.status_code, txt[:200])

                logger.warning("Evolution Baileys send failed: %d %s", resp.status_code, resp.text[:500])
                return None
        except Exception:
            logger.exception("Evolution Baileys send error")
            # Could not even reach Evolution — the route is down. One blip is
            # below threshold and scores nothing; repetition is a real signal.
            try:
                await record_event(self.org_id, self.instance, "disconnect", "send exception")
            except Exception:
                pass
            return None

    async def _send_meta(self, message: OutboundMessage) -> str | None:
        """Send via Meta Cloud API (through Evolution API bridge)."""
        if not self.instance or not self.api_key:
            logger.warning("Evolution Meta not configured: instance=%s", self.instance)
            return None

        if not await self._validate_url():
            return None

        to = (message.extra_data or {}).get("from_number") or self._config.get("default_number", "")
        if not to:
            logger.warning("No recipient number for Evolution Meta send")
            return None

        extra = message.extra_data or {}
        wtype = extra.get("whatsapp_type") or extra.get("type") or "text"

        # Same guard as the Baileys path. Without it the Meta path enforced
        # neither opt-out nor the 24h window (the delivery-layer pre-check
        # passes window_open=True by default), so every out-of-window free-form
        # reply drew a 131047 from Meta with no ban telemetry recorded.
        from aios.core.whatsapp_guard import guard_send

        try:
            ok, reason = await guard_send(
                to,
                message.text,
                is_template=(wtype == "template"),
                window_open=bool(extra.get("window_open", True)),
                provider="meta",
                instance=self.instance,
            )
            if not ok:
                logger.warning("Evolution Meta guard block %s: %s", to, reason)
                return None
        except Exception as e:
            logger.error(
                "Evolution Meta guard raised for to=%s; refusing to send: %s", to, e
            )
            return None

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                payload = self._build_meta_payload(wtype, to, message.text, extra)
                if not payload:
                    return None

                resp = await client.post(
                    f"{self.base_url}/message/sendWhatsApp/{self.instance}",
                    headers={"apikey": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    return data.get("key", {}).get("id") or data.get("messageId")

                logger.warning("Evolution Meta send failed: %d %s", resp.status_code, resp.text[:500])
                return None
        except Exception:
            logger.exception("Evolution Meta send error")
            return None

    def _build_meta_payload(self, wtype: str, to: str, text: str, extra: dict) -> dict | None:
        """Build Evolution Meta Cloud API payload."""
        payload: dict[str, Any] = {"number": to}

        if wtype == "template":
            tpl_name = extra.get("template_name") or self._config.get("template_name", "")
            if not tpl_name:
                logger.warning("Evolution Meta template send missing template_name")
                return None
            tpl_lang = extra.get("template_language") or self._config.get("template_language", "pt_BR")
            components = extra.get("template_components")
            if not components and extra.get("template_params"):
                params = extra["template_params"]
                if isinstance(params, list):
                    components = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}]
            payload["type"] = "template"
            payload["template"] = {"name": tpl_name, "language": {"code": tpl_lang}}
            if components:
                payload["template"]["components"] = components

        elif wtype in ("image", "document", "audio", "video", "sticker"):
            media_url = extra.get("media_url") or extra.get("url") or extra.get("link")
            media_id = extra.get("media_id") or extra.get("id")
            caption = text or extra.get("caption") or ""
            filename = extra.get("filename")
            if not media_url and not media_id:
                logger.warning("Evolution Meta media send missing url/id for %s", wtype)
                return None
            payload["mediatype"] = wtype
            media_obj: dict[str, Any] = {}
            if media_id:
                media_obj["id"] = media_id
            elif media_url:
                media_obj["link"] = media_url
            if caption and wtype in ("image", "document", "video"):
                media_obj["caption"] = caption[:1024]
            if filename and wtype == "document":
                media_obj["filename"] = filename
            payload["media"] = media_obj

        elif wtype == "interactive":
            itype = extra.get("interactive_type", "button")
            if itype == "button":
                body_text = extra.get("body_text") or text or ""
                buttons = extra.get("buttons") or []
                if not buttons:
                    payload["type"] = "text"
                    payload["text"] = body_text
                else:
                    payload["type"] = "interactive"
                    payload["interactive"] = {
                        "type": "button",
                        "body": {"text": body_text[:1024]},
                        "action": {"buttons": [{"type": "reply", "reply": {"id": b.get("id", f"btn_{i}"), "title": b.get("title", "")[:20]}} for i, b in enumerate(buttons[:3])]},
                    }
            else:
                body_text = extra.get("body_text") or text or ""
                sections = extra.get("sections") or [{"title": "Opções", "rows": extra.get("buttons", [])}]
                payload["type"] = "interactive"
                payload["interactive"] = {
                    "type": "list",
                    "body": {"text": body_text[:1024]},
                    "action": {"button": extra.get("button_text", "Ver opções")[:20], "sections": sections},
                }

        elif wtype == "location":
            lat = extra.get("latitude") or extra.get("lat")
            lon = extra.get("longitude") or extra.get("lon")
            if lat is not None and lon is not None:
                payload["type"] = "location"
                payload["location"] = {"latitude": float(lat), "longitude": float(lon), "name": extra.get("name", ""), "address": extra.get("address", "")}
            else:
                payload["type"] = "text"
                payload["text"] = text

        elif wtype == "contacts":
            payload["type"] = "contacts"
            payload["contacts"] = extra.get("contacts") or [{"name": {"formatted_name": extra.get("contact_name", "")}, "phones": [{"phone": to}]}]

        else:
            payload["type"] = "text"
            payload["text"] = text

        return payload

    async def _validate_url(self) -> bool:
        """Validate the configured Evolution server_url.

        Deliberately does NOT apply the SSRF private-IP block. Evolution is a
        first-party service on the internal Docker network
        (http://evolution:8080), so that guard made every send fail:
        _is_private("evolution") is True and both send paths bailed out before
        sending anything.

        server_url is operator config, not agent- or user-supplied input, so the
        SSRF threat model does not apply here. We still require a sane http(s)
        URL and reject embedded credentials.
        """
        from urllib.parse import urlparse

        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https"):
            logger.warning("Evolution send blocked: bad scheme %r", parsed.scheme)
            return False
        if not parsed.hostname:
            logger.warning("Evolution send blocked: server_url has no host")
            return False
        if parsed.username or parsed.password:
            logger.warning("Evolution send blocked: credentials in server_url")
            return False
        return True

    async def create_instance(self, instance_name: str, provider: str = "baileys", **kwargs) -> dict:
        """Create new Evolution instance (multi-tenant provisioning).

        Enforces plan-based instance limits.
        """
        if not self.api_key:
            return {"ok": False, "message": "Missing api_key for provisioning"}

        # Check plan limit
        limit_check = await self._check_instance_limit()
        if not limit_check["ok"]:
            return limit_check

        payload = {
            "instanceName": instance_name,
            "provider": provider,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS" if provider == "baileys" else "WHATSAPP-BUSINESS",
            **kwargs,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/instance/create",
                    headers={"apikey": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    # No webhook meant no inbound: the instance could send but
                    # never received, and nothing on the page said so.
                    hooked = await self._set_webhook(instance_name)
                    if not hooked.get("ok"):
                        logger.error(
                            "Instance %s created but webhook not set: %s",
                            instance_name, hooked.get("message"),
                        )
                    return {
                        "ok": True,
                        "data": resp.json(),
                        "webhook_ok": bool(hooked.get("ok")),
                        "webhook_error": None if hooked.get("ok") else hooked.get("message"),
                    }
                return {"ok": False, "message": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.exception("Evolution create_instance error")
            return {"ok": False, "message": str(e)}

    # provider -> Evolution integration. Verified against Evolution API v2.3.7:
    # WHATSAPP-CLOUD and BIZ_WEBHOOK are rejected as "Invalid integration".
    _INTEGRATION = {"baileys": "WHATSAPP-BAILEYS", "meta": "WHATSAPP-BUSINESS"}

    def meta_credentials(self) -> dict:
        """Meta Cloud API credentials as collected by the channel form."""
        return {
            "token": self._config.get("meta_token", ""),
            "number": self._config.get("meta_phone_id", ""),
            "instanceId": self._config.get("meta_waba_id", ""),
        }

    def missing_meta_credentials(self) -> list:
        return [f for f, v in self.meta_credentials().items() if not v]

    async def reconcile_provider(self) -> dict:
        """Make the Evolution side match config['provider'].

        The channel form only writes config, so flipping the provider selector
        changed which send path ran while the Evolution instance kept its
        original integration. A Meta payload sent to a WHATSAPP-BAILEYS instance
        fails. This reconciles the two.

        Provider-specific instances are kept side by side (`<name>-meta`) so
        switching back and forth does not destroy a WhatsApp pairing.

        Returns {"ok", "instance", "action", "message"} where action is one of
        ready | scan_qr | add_credentials | error.
        """
        provider = self.provider
        integration = self._INTEGRATION.get(provider)
        if not integration:
            return {"ok": False, "action": "error", "message": f"provider desconhecido: {provider!r}"}

        base = self.instance
        if not base:
            return {"ok": False, "action": "error", "message": "instance não configurado"}

        missing = self.missing_meta_credentials() if provider == "meta" else []
        if missing:
            names = {"token": "Meta access token", "number": "Phone number ID", "instanceId": "WABA ID"}
            return {
                "ok": False,
                "action": "add_credentials",
                "message": "Meta Cloud API precisa de: " + ", ".join(names[m] for m in missing),
            }

        # Reuse the base name for baileys so an existing pairing is never
        # disturbed; give meta its own name.
        target = base if provider == "baileys" else f"{base}-{provider}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base_url}/instance/fetchInstances",
                    headers={"apikey": self.api_key},
                )
                if resp.status_code != 200:
                    return {"ok": False, "action": "error", "message": f"Evolution API {resp.status_code}"}
                instances = resp.json() if isinstance(resp.json(), list) else []
        except Exception as e:
            logger.exception("Evolution reconcile: list failed")
            return {"ok": False, "action": "error", "message": str(e)}

        existing = next((i for i in instances if i.get("name") == target), None)
        if existing and existing.get("integration") != integration:
            # Right name, wrong transport — cannot be changed in place.
            existing = None

        if existing is None:
            payload = {
                "instanceName": target,
                "integration": integration,
                "qrcode": provider == "baileys",
                "options": {"deleteOnLogout": False, "delayOnStart": False, "trustQrCode": False},
            }
            if provider == "meta":
                payload.update(self.meta_credentials())
            try:
                async with httpx.AsyncClient(timeout=45) as client:
                    resp = await client.post(
                        f"{self.base_url}/instance/create",
                        headers={"apikey": self.api_key, "Content-Type": "application/json"},
                        json=payload,
                    )
            except Exception as e:
                logger.exception("Evolution reconcile: create failed")
                return {"ok": False, "action": "error", "message": str(e)}
            if resp.status_code not in (200, 201):
                return {"ok": False, "action": "error", "message": f"criação falhou: {resp.text[:200]}"}
            action = "scan_qr" if provider == "baileys" else "ready"
            msg = (
                f"Instância '{target}' criada — escaneie o QR no painel."
                if provider == "baileys"
                else f"Instância '{target}' criada com credenciais Meta."
            )
        else:
            state = existing.get("connectionStatus")
            if provider == "baileys" and state != "open":
                action, msg = "scan_qr", f"Instância '{target}' sem pareamento — escaneie o QR para conectar."
            else:
                action, msg = "ready", f"Instância '{target}' pronta ({state or 'ok'})."

        hooked = await self._set_webhook(target)
        if not hooked.get("ok"):
            return {"ok": False, "action": "error", "instance": target,
                    "message": f"instância ok, mas webhook falhou: {hooked.get('message')}"}

        return {"ok": True, "instance": target, "action": action, "message": msg}

    async def _set_webhook(self, instance_name: str) -> dict:
        """Point an instance's webhook at us, with the shared secret.

        Delegates to the single implementation in `evolution_api`, passing this
        channel's own key. The two call sites had drifted into different bodies
        — one nested (ignored by Evolution 2.x, so no URL was stored) and one
        with no `headers` at all (no secret, so auth failed).
        """
        from aios.core.evolution_api import evo_set_webhook

        res = await evo_set_webhook(instance_name, api_key=self.api_key)
        return {"ok": res.get("ok", False), "message": res.get("url") or res.get("message", "")}

    async def _check_instance_limit(self) -> dict:
        """Check if org has reached max Evolution instances for their plan."""
        if not self.db or not self.connection:
            return {"ok": True}  # skip check if no db/connection

        try:
            org_id = self.connection.org_id
            if not org_id:
                return {"ok": True}

            # Count existing evolution channels for this org
            from aios.db.models import ChannelConnection
            from sqlalchemy import select, func

            result = await self.db.execute(
                select(func.count(ChannelConnection.id)).where(
                    ChannelConnection.org_id == org_id,
                    ChannelConnection.channel_type == "evolution",
                    ChannelConnection.is_active == True,
                )
            )
            current_count = result.scalar() or 0

            # Get org's plan
            from aios.db.models import Organization
            org = await self.db.get(Organization, org_id)
            if not org:
                return {"ok": True}

            from aios.config import PLANS, settings
            if settings.internal_mode:
                return {"ok": True}  # ferramenta interna: sem limite de instâncias
            # Organization has no .plan column — the plan lives in extra_data.
            # Reading org.plan raised AttributeError, was swallowed, and the
            # limit check fail-opened for every org.
            plan_name = (org.extra_data or {}).get("plan", "free")
            plan = PLANS.get(plan_name, PLANS["free"])
            max_instances = plan.get("max_evolution_instances", 0)

            if max_instances > 0 and current_count >= max_instances:
                return {
                    "ok": False,
                    "message": f"Limite de instâncias WhatsApp atingido ({current_count}/{max_instances}). Plano {plan['name']} permite {max_instances} instância(s). Faça upgrade para mais."
                }

            return {"ok": True}
        except Exception as e:
            logger.warning("Instance limit check failed: %s", e)
            return {"ok": True}  # fail open

    async def delete_instance(self, instance_name: str) -> dict:
        """Delete Evolution instance."""
        if not self.api_key:
            return {"ok": False, "message": "Missing api_key"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.delete(
                    f"{self.base_url}/instance/delete/{instance_name}",
                    headers={"apikey": self.api_key},
                )
                return {"ok": resp.status_code in (200, 201, 204), "message": resp.text[:200] if resp.status_code >= 400 else "Deleted"}
        except Exception as e:
            logger.exception("Evolution delete_instance error")
            return {"ok": False, "message": str(e)}

    async def list_instances(self) -> dict:
        """List all Evolution instances."""
        if not self.api_key:
            return {"ok": False, "message": "Missing api_key"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/instance/fetchInstances",
                    headers={"apikey": self.api_key},
                )
                if resp.status_code == 200:
                    return {"ok": True, "instances": resp.json()}
                return {"ok": False, "message": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.exception("Evolution list_instances error")
            return {"ok": False, "message": str(e)}

    async def get_instance_qrcode(self, instance_name: str) -> dict:
        """Get QR code for Baileys instance connection."""
        if not self.api_key:
            return {"ok": False, "message": "Missing api_key"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/instance/connect/{instance_name}",
                    headers={"apikey": self.api_key},
                )
                if resp.status_code == 200:
                    return {"ok": True, "data": resp.json()}
                return {"ok": False, "message": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.exception("Evolution get_instance_qrcode error")
            return {"ok": False, "message": str(e)}

    async def start(self) -> None:
        logger.info("Evolution API channel %s (%s) ready", self.instance, self.provider)

    async def stop(self) -> None:
        pass

    async def test(self) -> dict:
        if not await self._validate_url():
            return {"ok": False, "message": "server_url must be a public URL"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/instance/fetchInstances",
                    headers={"apikey": self.api_key},
                )
                if resp.status_code == 200:
                    instances = resp.json()
                    found = any(i.get("name") == self.instance for i in (instances if isinstance(instances, list) else []))
                    if found:
                        return {"ok": True, "message": f"Instance '{self.instance}' found and API connected ({self.provider})"}
                    return {"ok": True, "message": f"API connected ({self.provider}) — instance check skipped"}
                return {"ok": False, "message": f"API error: {resp.status_code}"}
        except Exception as e:
            logger.exception("Evolution API test failed")
            return {"ok": False, "message": str(e)}