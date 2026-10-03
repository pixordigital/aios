"""Webhooks and integrations that no provider could ever reach.

Each of these compared a digest computed one way against a header sent
another way, so the endpoint accepted nothing in production while the UI and
the plan advertised it.
"""

import base64
import hashlib
import hmac
import inspect
import pathlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunsplit

import pytest

from aios.api.voice_webhook import _verify_twilio_signature

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOKEN = "auth-token-123"
URL = "https://aios.example.com/api/voice/webhook"


class _Req:
    def __init__(self, signature, body, url=URL, query=None):
        self.url = url
        self.headers = {"x-twilio-signature": signature} if signature else {}
        self.query_params = query or {}
        self._body = body if isinstance(body, bytes) else body.encode()

    async def body(self):
        return self._body


def _twilio_sig(body: str, token: str = TOKEN) -> str:
    """Sign exactly the way Twilio documents: url without query, then each
    POST field concatenated name+value, both sorted."""
    p = urlparse(URL)
    base = urlunsplit((p.scheme, p.netloc, p.path, "", ""))
    fields = sorted(k + v for k, v in parse_qsl(body, keep_blank_values=True))
    raw = base + "".join(fields)
    return base64.b64encode(
        hmac.new(token.encode(), raw.encode(), hashlib.sha1).digest()
    ).decode()


# ─── Twilio ───────────────────────────────────────────────────────────────

def test_twilio_accepts_a_genuinely_signed_request(monkeypatch):
    """The endpoint required an `x-voice-signature` header holding
    hex(HMAC-SHA256(secret, body)). Twilio sends X-Twilio-Signature =
    base64(HMAC-SHA1(auth_token, url + sorted params)) — a different header and
    a different construction, so every real call event 401'd."""
    from aios.api import voice_webhook as V
    from aios.config import settings

    monkeypatch.setattr(settings, "voice_webhook_secret", TOKEN, raising=False)
    body = urlencode({"CallSid": "CA1", "From": "+5511", "To": "+5522"})
    assert _verify_twilio_signature(_Req(_twilio_sig(body), body), body.encode()) is True


def test_twilio_rejects_tampering_and_forgeries(monkeypatch):
    from aios.api import voice_webhook as V  # noqa: F401
    from aios.config import settings

    monkeypatch.setattr(settings, "voice_webhook_secret", TOKEN, raising=False)
    body = urlencode({"CallSid": "CA1", "From": "+5511"})

    tampered = body + "&To=%2B5599"
    assert _verify_twilio_signature(_Req(_twilio_sig(body), tampered), tampered.encode()) is False

    forged = base64.b64encode(b"x" * 20).decode()
    assert _verify_twilio_signature(_Req(forged, body), body.encode()) is False

    assert _verify_twilio_signature(_Req("", body), body.encode()) is False

    # wrong auth token must not validate
    assert _verify_twilio_signature(
        _Req(_twilio_sig(body, "other-token"), body), body.encode()
    ) is False


# ─── Mailgun ──────────────────────────────────────────────────────────────

def _mailgun_sig(body: str, timestamp: str, secret: str) -> str:
    return hmac.new(
        secret.encode(), (timestamp + body).encode(), hashlib.sha256
    ).hexdigest()


def test_mailgun_signature_scheme(monkeypatch):
    from aios.api import email_webhook as E
    from aios.config import settings

    secret = "mg-secret"
    monkeypatch.setattr(settings, "mailgun_webhook_secret", secret, raising=False)
    body, ts = "recipient=ana%40x.com&text=oi", "1700000000"
    sig = _mailgun_sig(body, ts, secret)

    class Req:
        url = "https://x/api/email/webhook"
        headers = {"x-mailgun-signature": f"{ts},{sig}"}
        query_params = {}

    assert E._verify_email_signature(Req(), body.encode(), "mailgun") is True
    # wrong timestamp prefix must not validate
    Req.headers = {"x-mailgun-signature": f"1700000001,{sig}"}
    assert E._verify_email_signature(Req(), body.encode(), "mailgun") is False


def test_asymmetric_providers_fail_closed_rather_than_faking_it():
    """SendGrid is ECDSA over ts+body with the app's public key and SNS is
    RSA-SHA256; neither is checkable with a shared secret, so they refuse
    loudly instead of comparing a digest that can never match. The two settings
    fields that implied otherwise are gone."""
    from aios.api import email_webhook as E
    from aios.config import settings

    assert not hasattr(settings, "sendgrid_webhook_secret")
    assert not hasattr(settings, "ses_webhook_secret")

    class Req:
        url = "https://x/api/email/webhook"
        headers = {"x-twilio-email-event-webhook-signature": "whatever"}
        query_params = {}

    assert E._verify_email_signature(Req(), b"{}", "sendgrid") is False
    assert E._verify_email_signature(Req(), b"{}", "ses") is False
    assert E._verify_email_signature(Req(), b"{}", "unknown-provider") is False


def test_email_webhook_has_no_generic_hmac_shortcut():
    """The old code computed one HMAC-SHA256 hex digest of the body and
    compared it to every provider's header."""
    from aios.api.email_webhook import _verify_email_signature

    src = inspect.getsource(_verify_email_signature)
    assert "hashlib.sha256).hexdigest()" not in src, (
        "still using the one-digest-for-every-provider scheme"
    )


# ─── email poller bypassed the whole delivery pipeline ────────────────────

def test_imap_poller_uses_dispatch_inbound():
    """It called AgentRuntime inline with "email_<uid>" as the conversation id:
    no Conversation row, no Message rows, no check_org_limits, no retry and no
    DLQ. A failed reply vanished into a log line."""
    from aios.channels.email_ import EmailChannel

    src = inspect.getsource(EmailChannel._poll_loop)
    assert "dispatch_inbound" in src
    assert "AgentRuntime(" not in src, "the poller still runs the agent inline"
    assert '"email_" + uid_str' not in src, "still using a synthetic conversation id"
    # the IMAP UID is this provider's stable message id — use it for dedup
    assert "msg_id" in src


def test_email_reply_carries_the_sender_forward():
    """The reply is now dispatched rather than sent inline, so the sender has
    to travel in extra_data or the agent's answer has nowhere to go."""
    from aios.channels.email_ import EmailChannel

    src = inspect.getsource(EmailChannel._poll_loop)
    assert "from_email" in src


# ─── ARVO events that will never be delivered ─────────────────────────────

def test_exhausted_outbox_rows_notify_a_human():
    """A row past its retry budget went to status="failed" and stayed there:
    no alert, no audit entry, and the flush counter looked like ordinary
    backoff."""
    from aios.integrations.arvo import publisher

    src = inspect.getsource(publisher._deliver)
    assert "_notify_exhausted" in src, "an exhausted row is still silent"
    assert 'logger.error' in inspect.getsource(publisher._notify_exhausted)

    flush = inspect.getsource(publisher.flush_outbox)
    assert "exhausted" in flush, "exhausted rows are not counted apart from retries"