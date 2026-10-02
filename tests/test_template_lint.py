"""Regression tests for the deterministic template linter.

Every rule here corresponds to a rejection reason Meta documents, or to a check
Meta does not expose at all (duplication, sensitive identifiers). The linter is
the primary gate on first-pass approval, so each rule is pinned individually
rather than asserted in bulk.

These are pure-function tests: no network, no database, no LLM.
"""

import pytest

from aios.core.template_lint import (
    TemplateDraft,
    can_submit,
    errors,
    lint_template,
    summarise,
    warnings,
)


def ids(draft) -> list:
    return [f.rule_id for f in lint_template(draft)]


def clean(**kw) -> TemplateDraft:
    base = dict(
        name="lembrete_consulta",
        category="UTILITY",
        body="Ola {{1}}, confirmamos sua consulta de {{2}} para o dia de amanha.",
        examples={"1": "Joao", "2": "12/03"},
    )
    base.update(kw)
    return TemplateDraft(**base)


# ── the happy path must stay clean ──────────────────────────────────────

def test_clean_template_has_no_errors():
    f = lint_template(clean())
    assert can_submit(f), [x.as_dict() for x in errors(f)]
    assert errors(f) == []


def test_summary_does_not_claim_approval():
    """The linter must never promise approval — Meta reviews it."""
    s = summarise(lint_template(clean()))
    assert "Meta" in s
    assert "aprovado" not in s.lower() or "rejeitar" in s.lower()


# ── name rules ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["Bad Name", "with-dash", "UPPER", "acentuação", ""])
def test_bad_names_rejected(name):
    assert any(i.startswith("name.") for i in ids(clean(name=name)))


def test_name_too_long():
    assert "name.too_long" in ids(clean(name="a" * 513))


def test_name_underscores_digits_allowed():
    assert "name.charset" not in ids(clean(name="reengajamento_01_v2"))


# ── parameter rules ──────────────────────────────────────────────────────

def test_non_sequential_parameters_rejected():
    assert "params.sequence" in ids(clean(body="Ola {{1}} e {{3}} passagem confirmada.", examples={"1": "a", "3": "c"}))


def test_unmatched_braces_rejected():
    assert "params.braces" in ids(clean(body="Ola {{1}} sua consulta {2} confirmada."))


def test_dangling_start_rejected():
    assert "params.dangling" in ids(clean(body="{{1}} sua consulta foi confirmada."))


def test_dangling_end_rejected():
    assert "params.dangling" in ids(clean(body="Sua consulta foi confirmada {{2}}", examples={"1": "a", "2": "b"}))


def test_floating_parameter_line_rejected():
    """A line containing only variables is a documented rejection."""
    d = clean(body="Segue os dados:\n{{1}}\n{{2}}\nAtenciosamente", examples={"1": "a", "2": "b"})
    assert "params.floating" in ids(d)


def test_missing_example_rejected():
    """Meta requires an example value per parameter at creation time."""
    d = clean(body="Ola {{1}} e {{2}}, tudo certo.", examples={"1": "a"})
    assert "params.example_missing" in ids(d)


def test_example_placeholder_blank_rejected():
    d = clean(body="Ola {{1}}, tudo certo.", examples={"1": "   "})
    assert "params.example_missing" in ids(d)


def test_too_many_variables_is_warning_not_error():
    """Too many variables is empirical guidance — it must not hard-block."""
    d = clean(body="{{1}} {{2}} {{3}} {{4}}", examples={str(i): "x" for i in range(1, 5)})
    f = lint_template(d)
    assert "params.ratio" in [x.rule_id for x in warnings(f)]


# ── footer / header rules ────────────────────────────────────────────────

def test_footer_with_variable_rejected():
    assert "footer.no_params" in ids(clean(footer="{{1}}"))


def test_footer_too_long_rejected():
    assert "footer.too_long" in ids(clean(footer="a" * 61))


def test_footer_with_formatting_rejected():
    assert "footer.formatting" in ids(clean(footer="*Obrigado*"))


def test_header_with_formatting_rejected():
    assert "header.formatting" in ids(clean(header_text="*Aviso*"))


# ── policy rules ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    "Envie seu CPF 12345678909 para confirmacao.",
    "Informe o numero completo do cartao 4111111111111111.",
    "Voce pode ser processado por falta de pagamento.",
])
def test_sensitive_content_rejected(body):
    assert "policy.sensitive" in ids(clean(body=body))


def test_promotional_wording_rejected_in_utility():
    assert "category.mismatch" in ids(clean(body="Aproveite nossa oferta imperdivel de desconto hoje."))


def test_promotional_wording_allowed_in_marketing():
    d = clean(category="MARKETING", body="Aproveite nossa oferta imperdivel de desconto hoje.")
    assert "category.mismatch" not in ids(d)


# ── duplication: not obtainable from Meta ───────────────────────────────

def test_duplicate_detected_despite_accents():
    d = clean(body="Ola {{1}} seu pedido saiu hoje.", existing_bodies=["Olá {{1}} seu pedido saiu hoje."])
    assert "duplicate.content" in ids(d)


def test_duplicate_detected_despite_punctuation():
    d = clean(body="Ola {{1}}, seu pedido saiu!", existing_bodies=["olá {{1}} seu pedido saiu"])
    assert "duplicate.content" in ids(d)


def test_duplicate_ignores_parameter_names():
    """Meta compares content; {{1}} vs {{9}} is the same wording."""
    d = clean(body="Ola {{1}} seu pedido saiu", existing_bodies=["Ola {{9}} seu pedido saiu"])
    assert "duplicate.content" in ids(d)


def test_different_wording_is_not_duplicate():
    d = clean(body="Ola {{1}} seu pedido saiu", existing_bodies=["Ola {{1}} sua fatura venceu"])
    assert "duplicate.content" not in ids(d)


def test_empty_existing_list_is_fine():
    d = clean(existing_bodies=[])
    assert can_submit(lint_template(d))


# ── body required ────────────────────────────────────────────────────────

def test_empty_body_rejected():
    assert "body.required" in ids(clean(body=""))


# ── result shape ─────────────────────────────────────────────────────────

def test_findings_serialise_for_the_editor():
    f = lint_template(clean(name="BAD", body="{{1}}oi"))
    d = [x.as_dict() for x in f]
    assert d, "expected findings"
    for item in d:
        assert set(item) == {"severity", "rule_id", "message", "field", "span"}
        assert item["severity"] in ("error", "warning")


@pytest.mark.parametrize("body", [
    "{{1}} sua consulta confirmada",          # leading
    "   {{1}} sua consulta confirmada",       # leading + whitespace
    "sua consulta confirmada {{2}}",          # trailing
    "sua consulta confirmada {{2}}   ",       # trailing + whitespace
])
def test_span_points_at_the_offending_text(body):
    """Spans index into the text the user typed, whitespace included."""
    d = clean(body=body, examples={"1": "a", "2": "b"})
    f = [x for x in lint_template(d) if x.rule_id == "params.dangling"]
    assert f, "expected a dangling finding"
    for finding in f:
        start, end = finding.span
        assert body[start:end].strip().startswith("{{"), (body[start:end], body)


def test_can_submit_requires_zero_errors_only():
    """A ratio warning must never hard-block a submission."""
    d = clean(
        body="Total {{1}} itens {{2}} reais de frete para {{3}} em {{4}} ok",
        examples={str(i): "x" for i in range(1, 5)},
    )
    f = lint_template(d)
    assert warnings(f), "expected the ratio warning"
    assert errors(f) == [], [x.as_dict() for x in errors(f)]
    assert can_submit(f), "warnings must not block submission"


def test_linter_is_pure():
    """Same input, same output, no mutation of the draft."""
    d = clean()
    before = (d.name, d.body, dict(d.examples))
    a = [x.as_dict() for x in lint_template(d)]
    b = [x.as_dict() for x in lint_template(d)]
    assert a == b
    assert (d.name, d.body, dict(d.examples)) == before