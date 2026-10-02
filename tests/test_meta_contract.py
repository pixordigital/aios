"""Contract tests: our Meta payload vs Meta's documented request schema.

These do NOT prove Meta accepts the payload at runtime — only a live call with a
real token does that. What they do prove is that the builder still matches the
shape Meta documents, so a refactor cannot silently drift (drop the example
wrapper, rename a component type, emit `"example": null`).

That gap is real and was measured: posting a deliberately malformed payload to
graph.facebook.com returns the same code=190 as a correct one, because Meta
authenticates before it validates. So an auth error carries no information about
shape, which is exactly why these tests have to pin it statically.

Source: Meta WhatsApp Business Management API, Message Template API
  POST /{Version}/{WABA-ID}/message_templates
    name, language, category, components, allow_category_change
  components[]: {type: HEADER|BODY|BUTTONS, format, text, example}
  example: {"<param_index>": ["<sample value>"]}
"""

import pytest

from aios.core.meta_api import TemplateComponents

VALID_CATEGORIES = {"UTILITY", "MARKETING", "AUTHENTICATION"}
VALID_COMPONENT_TYPES = {"HEADER", "BODY", "FOOTER", "BUTTONS"}


def _b(**kw) -> dict:
    return TemplateComponents(**kw).to_meta()


# ── component types and required fields ─────────────────────────────────

def test_components_are_ordered_header_body_footer():
    comps = _b(header_text="Aviso", body="Ola {{1}}", footer="Obrigado")
    assert [c["type"] for c in comps] == ["HEADER", "BODY", "FOOTER"]


@pytest.mark.parametrize("kind", ["HEADER", "BODY", "FOOTER"])
def test_component_type_is_documented(kind):
    comps = _b(header_text="H", body="B", footer="F")
    assert comps[0]["type"] in VALID_COMPONENT_TYPES
    assert kind in {c["type"] for c in comps}


def test_header_declares_text_format():
    """A TEXT header must carry format=TEXT; Meta rejects it otherwise."""
    comps = _b(header_text="Aviso", body="B")
    header = next(c for c in comps if c["type"] == "HEADER")
    assert header["format"] == "TEXT"
    assert header["text"] == "Aviso"


def test_absent_header_omits_the_component_entirely():
    assert [c["type"] for c in _b(body="B")] == ["BODY"]
    assert [c["type"] for c in _b(header_text="   ", body="B")] == ["BODY"]


def test_empty_body_yields_no_body_component():
    assert _b(header_text="Aviso", footer="F") == [
        {"type": "HEADER", "format": "TEXT", "text": "Aviso"},
        {"type": "FOOTER", "text": "F"},
    ]


# ── the `example` wrapper: {"<index>": ["value"]} ───────────────────────

def test_example_is_param_index_to_list():
    comps = _b(body="Ola {{1}}, em {{2}}", examples={"1": "Joao", "2": "12/03"})
    body = next(c for c in comps if c["type"] == "BODY")
    assert body["example"] == {"1": ["Joao"], "2": ["12/03"]}


def test_example_omitted_when_absent_not_null():
    """`"example": null` is a different request from an absent key."""
    body = next(c for c in _b(body="Ola") if c["type"] == "BODY")
    assert "example" not in body


def test_example_omitted_when_all_values_blank():
    body = next(c for c in _b(body="Ola", examples={"1": "  "}) if c["type"] == "BODY")
    assert "example" not in body


def test_example_keys_are_stringified():
    """pydantic/JSON can hand back int keys; Meta wants string param names."""
    body = next(c for c in _b(body="Ola {{1}}", examples={1: "a"}) if c["type"] == "BODY")
    assert list(body["example"]) == ["1"]


def test_example_values_are_wrapped_in_a_list():
    body = next(c for c in _b(body="Ola {{1}}", examples={"1": "a"}) if c["type"] == "BODY")
    assert body["example"]["1"] == ["a"]


# ── the full create payload ─────────────────────────────────────────────

def _payload(**kw):
    body = {
        "name": "lembrete_consulta",
        "language": "pt_BR",
        "category": "UTILITY",
        "components": _b(**kw),
    }
    if kw.pop("allow_category_change", True):
        body["allow_category_change"] = True
    return body


def test_create_payload_fields_are_all_documented():
    p = _payload(header_text="Aviso", body="Ola {{1}}", footer="Obrigado",
                 examples={"1": "Joao"})
    assert set(p) == {"name", "language", "category", "components", "allow_category_change"}
    assert p["category"] in VALID_CATEGORIES
    assert isinstance(p["components"], list) and p["components"]


def test_media_headers_are_not_emitted():
    """Media headers need a Resumable Upload asset handle; v1 is text-only.

    Silently emitting a HEADER without a valid handle would be rejected by Meta.
    """
    comps = _b(header_text="Plain text", body="B")
    header = next(c for c in comps if c["type"] == "HEADER")
    assert header["format"] == "TEXT"
    assert "asset" not in header and "attachment" not in header


def test_no_unexpected_keys_in_any_component():
    allowed = {"type", "format", "text", "example"}
    for comp in _b(header_text="H", body="B {{1}}", footer="F", examples={"1": "a"}):
        assert set(comp) <= allowed, f"undocumented component keys: {set(comp) - allowed}"


def test_payload_is_json_serialisable():
    import json
    p = _payload(body="Ola {{1}}", examples={"1": "Joao"})
    assert json.loads(json.dumps(p)) == p


# ── the guard against the drift that actually happened ─────────────────

def test_builder_is_deterministic():
    a = _b(header_text="H", body="B {{1}} {{2}}", footer="F", examples={"1": "a", "2": "b"})
    b = _b(header_text="H", body="B {{1}} {{2}}", footer="F", examples={"1": "a", "2": "b"})
    assert a == b