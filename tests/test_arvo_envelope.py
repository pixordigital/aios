"""Canonical ARVO ↔ AIOS envelope schema and wire format."""

import json

import httpx
import pytest
from pydantic import ValidationError

from aios.integrations.arvo.events import MAX_PAYLOAD_BYTES, ArvoEnvelope


def test_envelope_version_round_trip():
    raw = json.dumps({"type": "test.event", "payload": {"a": 1}, "business_trace_id": "trace-1"}).encode()
    legacy = ArvoEnvelope.model_validate_json(raw)
    assert legacy.event_version == "1"
    assert legacy.business_trace_id == "trace-1"

    reparsed = ArvoEnvelope.model_validate_json(legacy.model_dump_json())
    assert reparsed == legacy

    explicit = ArvoEnvelope(type="test.event", payload={"a": 1}, event_version="2")
    assert ArvoEnvelope.model_validate_json(explicit.model_dump_json()).event_version == "2"


@pytest.mark.parametrize("field,value", [
    ("type", "BAD TYPE"),
    ("event_version", "v 1"),
    ("event_version", "x" * 17),
    ("payload", {"blob": "x" * (MAX_PAYLOAD_BYTES + 1)}),
])
def test_envelope_rejects_invalid_fields(field, value):
    data = {"type": "test.event", "payload": {}, "event_version": "1"}
    data[field] = value
    with pytest.raises(ValidationError):
        ArvoEnvelope(**data)


async def test_client_emits_canonical_envelope(monkeypatch):
    from aios.config import settings
    from aios.integrations.arvo import client

    captured = {}

    async def fake_request(method, path, **kwargs):
        captured.update(kwargs)
        return httpx.Response(
            200, request=httpx.Request(method, f"http://peer.test{path}"), json={"status": "ok"}
        )

    monkeypatch.setattr(client, "_request_with_retry", fake_request)
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid")
    monkeypatch.setattr(settings, "arvo_service_key", "secret")

    assert await client.send_event("test.event", {"a": 1}, business_trace_id="trace-1") == {"status": "ok"}
    envelope = ArvoEnvelope.model_validate_json(captured["content"])
    assert envelope.type == "test.event"
    assert envelope.payload == {"a": 1}
    assert envelope.business_trace_id == "trace-1"
    assert envelope.event_version == "1"
