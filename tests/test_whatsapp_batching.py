"""Outbound bubble batching: N quick texts → 1 WhatsApp message, 1 fee.

Each test names the property it pins, because a batcher that silently drops,
reorders, or merges the wrong things is worse than no batcher.
"""

import asyncio
import time
import types

import pytest

from aios.channels import evolution as evo_mod
from aios.channels.base import OutboundMessage
from aios.config import settings


def _conn(**cfg):
    base = {"instance": "inst-1", "api_key": "k", "provider": "baileys",
            "server_url": "http://evolution:8080"}
    base.update(cfg)
    return types.SimpleNamespace(config=base, org_id="o1")


def _msg(text, conv="c1", extra=None, chan="ch1"):
    return OutboundMessage(
        conversation_id=conv, text=text,
        channel_connection_id=chan,
        extra_data=dict({"from_number": "5511999999999"}, **(extra or {})),
    )


@pytest.fixture
def fast_window(monkeypatch):
    """Short window so bursts flush fast; restored after each test."""
    monkeypatch.setattr(settings, "whatsapp_batch_enabled", True)
    monkeypatch.setattr(settings, "whatsapp_batch_window_sec", 0.05)
    monkeypatch.setattr(settings, "whatsapp_batch_max_messages", 5)
    monkeypatch.setattr(settings, "whatsapp_batch_max_chars", 3800)
    yield
    evo_mod._buffers.clear()
    for t in list(evo_mod._flush_tasks.values()):
        t.cancel()
    evo_mod._flush_tasks.clear()


def _dispatch_recorder(calls, result="prov-id-1"):
    async def _send(message):
        calls.append(message.text)
        return result
    return _send


# ─── merge rules ──────────────────────────────────────────────────────────

def test_plain_text_is_mergeable():
    assert evo_mod._mergeable(_msg("oi")) is True
    assert evo_mod._mergeable(_msg("oi", extra={"type": "text"})) is True


def test_templates_and_typed_messages_never_merge():
    """A template joined into a text bubble would go out as free text and draw
    a 131047 outside the 24h window — or lose its parameters inside it."""
    assert evo_mod._mergeable(_msg("oi", extra={"is_template": True})) is False
    assert evo_mod._mergeable(_msg("oi", extra={"type": "template"})) is False
    assert evo_mod._mergeable(_msg("oi", extra={"type": "image"})) is False
    assert evo_mod._mergeable(_msg("oi", extra={"type": "audio"})) is False
    assert evo_mod._mergeable(_msg("oi", extra={"whatsapp_type": "interactive"})) is False


# ─── batching behavior ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_burst_becomes_one_bubble(fast_window, monkeypatch):
    """The core claim: 3 quick sends → 1 provider call, joined text, and every
    caller gets the provider id (their text is inside that bubble)."""
    calls = []
    monkeypatch.setattr(
        evo_mod.EvolutionChannel, "_dispatch", lambda self, m: _dispatch_recorder(calls)(m)
    )
    ch = evo_mod.EvolutionChannel(connection=_conn())
    results = await asyncio.gather(
        ch.send(_msg("um")), ch.send(_msg("dois")), ch.send(_msg("três")),
    )
    assert calls == ["um dois três"]
    assert results == ["prov-id-1"] * 3


@pytest.mark.asyncio
async def test_template_flushes_pending_first_and_goes_alone(fast_window, monkeypatch):
    """Order is preserved (pending texts first) and the template is never
    merged into the bubble."""
    calls = []
    monkeypatch.setattr(
        evo_mod.EvolutionChannel, "_dispatch", lambda self, m: _dispatch_recorder(calls)(m)
    )
    ch = evo_mod.EvolutionChannel(connection=_conn())
    pending = asyncio.ensure_future(ch.send(_msg("antes")))
    await asyncio.sleep(0.01)  # let it buffer
    tpl_id = await ch.send(_msg("tpl-body", extra={"is_template": True}))
    first_id = await pending
    assert calls == ["antes", "tpl-body"], f"order or merge broken: {calls}"
    assert first_id == tpl_id == "prov-id-1"


@pytest.mark.asyncio
async def test_recipients_never_mix(fast_window, monkeypatch):
    calls = []

    async def _send(self, message):
        calls.append((message.extra_data["from_number"], message.text))
        return "id"

    monkeypatch.setattr(evo_mod.EvolutionChannel, "_dispatch", _send)
    ch = evo_mod.EvolutionChannel(connection=_conn())

    def _to(text, num):
        return _msg(text, extra={"from_number": num})

    await asyncio.gather(
        ch.send(_to("a1", "5511000000001")), ch.send(_to("b1", "5511000000002")),
    )
    assert sorted(calls) == [
        ("5511000000001", "a1"), ("5511000000002", "b1"),
    ], f"tenants/recipients mixed: {calls}"


@pytest.mark.asyncio
async def test_message_cap_flushes_early(fast_window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        evo_mod.EvolutionChannel, "_dispatch", lambda self, m: _dispatch_recorder(calls)(m)
    )
    ch = evo_mod.EvolutionChannel(connection=_conn())
    await asyncio.gather(*[ch.send(_msg(f"m{i}")) for i in range(6)])
    assert len(calls) == 2, f"expected 5+1 bubbles, got: {calls}"
    assert calls == ["m0 m1 m2 m3 m4", "m5"]


@pytest.mark.asyncio
async def test_char_cap_flushes_early(fast_window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        evo_mod.EvolutionChannel, "_dispatch", lambda self, m: _dispatch_recorder(calls)(m)
    )
    ch = evo_mod.EvolutionChannel(connection=_conn())
    big = "x" * 3000
    await asyncio.gather(ch.send(_msg(big)), ch.send(_msg(big)))
    assert len(calls) == 2, "two 3000-char texts must not merge past the cap"


@pytest.mark.asyncio
async def test_unconfigured_channel_skips_the_window(fast_window, monkeypatch):
    """No instance/key: today's direct None, without making the caller sit
    out the batch window first."""
    monkeypatch.setattr(
        evo_mod.EvolutionChannel, "_dispatch", lambda self, m: _dispatch_recorder([])(m)
    )
    ch = evo_mod.EvolutionChannel(connection=_conn(instance="", api_key=""))
    start = time.monotonic()
    assert await ch.send(_msg("oi")) == "prov-id-1"
    assert time.monotonic() - start < 0.05, "unconfigured send waited for the window"


@pytest.mark.asyncio
async def test_kill_switch_restores_direct_send(fast_window, monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "whatsapp_batch_enabled", False)
    monkeypatch.setattr(
        evo_mod.EvolutionChannel, "_dispatch", lambda self, m: _dispatch_recorder(calls)(m)
    )
    ch = evo_mod.EvolutionChannel(connection=_conn())
    await asyncio.gather(ch.send(_msg("a")), ch.send(_msg("b")))
    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_all_cancelled_waiters_send_nothing(fast_window, monkeypatch):
    """Cancelled deliver jobs are retried upstream; sending anyway would orphan
    a bubble AND duplicate it on retry."""
    calls = []
    monkeypatch.setattr(
        evo_mod.EvolutionChannel, "_dispatch", lambda self, m: _dispatch_recorder(calls)(m)
    )
    ch = evo_mod.EvolutionChannel(connection=_conn())
    tasks = [asyncio.ensure_future(ch.send(_msg(f"t{i}"))) for i in range(2)]
    await asyncio.sleep(0.01)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0.15)  # past the window
    assert calls == [], f"orphan bubble sent for cancelled callers: {calls}"


def test_merged_message_keeps_routing_fields():
    """The bubble carries the first message's ids/extra: delivery stamps each
    logical send under its own idempotency key, and the provider id is only
    checked for None-ness — so sharing one provider id is safe."""
    first = _msg("a", conv="c9", chan="ch9", extra={"msg_id": "in-1"})
    merged = evo_mod._merged_message(first, ["a", "b"])
    assert merged.text == "a b"  # "b" continues the sentence — see _join_texts
    assert merged.conversation_id == "c9"
    assert merged.channel_connection_id == "ch9"
    assert merged.extra_data["from_number"] == "5511999999999"


# ─── smart join ───────────────────────────────────────────────────────────

def test_fragments_flow_into_one_sentence():
    """The case that motivated this: "hi" / "your order number is:" /
    "diri38rifir" must read as one message, not three stacked paragraphs."""
    assert evo_mod._join_texts(
        ["hi", "your order number is:", "diri38rifir"]
    ) == "hi your order number is: diri38rifir"


def test_label_value_joins_with_space():
    assert evo_mod._join_texts(["your number is:", "49349"]) == "your number is: 49349"
    assert evo_mod._join_texts(["total:", "R$ 42,00"]) == "total: R$ 42,00"


def test_lowercase_continuation_joins_with_space():
    assert evo_mod._join_texts(["Seu pedido saiu", "chega em 20 min"]) == (
        "Seu pedido saiu chega em 20 min"
    )


def test_new_sentence_keeps_paragraph_break():
    assert evo_mod._join_texts(["Oi!", "Seu pedido chegou"]) == "Oi!\n\nSeu pedido chegou"
    assert evo_mod._join_texts(["ok", "Vou verificar"]) == "ok\n\nVou verificar"


def test_list_items_keep_paragraph_breaks():
    """Digits don't read as continuations, so numbered lists stay stacked."""
    assert evo_mod._join_texts(["1. leite", "2. ovos"]) == "1. leite\n\n2. ovos"


def test_mixed_burst_joins_selectively():
    assert evo_mod._join_texts(
        ["hi", "seu pedido:", "123", "Obrigado pela preferência!"]
    ) == "hi seu pedido: 123\n\nObrigado pela preferência!"


def test_whitespace_only_parts_are_dropped():
    assert evo_mod._join_texts(["", "  ", "oi"]) == "oi"
    # ...but a lone empty send behaves exactly as it does today (sent as-is)
    assert evo_mod._join_texts([""]) == ""
    assert evo_mod._join_texts([]) == ""
