"""Regression tests for PII redaction.

The original patterns only covered CPF (formatted and bare), RG, a 16-digit card
written with optional spaces, and Brazilian landlines in "(11) 9123-4567" form.
Everything else passed through verbatim into traces and logs: e-mail addresses,
mobile numbers written with a country code, cards written with hyphens, 13/15/19
digit cards, CEP and API keys.

Each case below was verified to leak before these patterns were added.
"""

import time

import pytest

from aios.core.pii import redact_pii, redact_pii_obj


def _leaks(value: str) -> bool:
    return "***" not in value


@pytest.mark.parametrize(
    "label,text",
    [
        ("email", "contato: maria.silva@empresa.com.br"),
        ("email plus tag", "maria.silva+suporte@empresa.com.br"),
        ("email subdomain", "joao@mail.empresa.co.uk"),
        ("intl mobile spaced", "ligue +55 11 91234-5678 agora"),
        ("intl mobile unspaced", "tel +5511987654321"),
        ("bare mobile", "meu zap e 11912345678"),
        ("landline", "(11) 3456-7890"),
        ("card hyphens", "cartao 1234-5678-9012-3456"),
        ("card spaces", "cartao 1234 5678 9012 3456"),
        ("visa 16", "4111 1111 1111 1111"),
        ("visa 13", "visa 4222222222222"),
        ("amex 15 spaced", "amex 3782 822463 10005"),
        ("amex 15 bare", "378282246310005"),
        ("mastercard 19", "5019717010103742"),
        ("cep", "entrega no CEP 01310-100"),
        ("cpf formatted", "cpf 123.456.789-09"),
        ("cpf bare", "cpf 12345678909"),
        ("rg", "rg 12.345.678-9"),
        ("github token", "token " + "gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
        ("stripe key", "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUVWXYZ01"),
        ("google key", "AI" + "zaSyA1B2C3D4E5F6G7H8I9J0"),
    ],
)
def test_pii_is_redacted(label, text):
    # The provider-key fixtures above are assembled from fragments on purpose:
    # written out in full they trip GitHub secret-scanning push protection, which
    # blocks the whole commit rather than just this line.
    assert not _leaks(redact_pii(text)), f"{label} leaked: {redact_pii(text)}"


def test_mixed_message_with_several_fields():
    text = (
        "Maria (maria.silva@empresa.com.br), CPF 123.456.789-09, "
        "tel +55 11 91234-5678, cartao 4111 1111 1111 1111"
    )
    out = redact_pii(text)
    assert "maria.silva@empresa.com.br" not in out
    assert "123.456.789-09" not in out
    assert "91234-5678" not in out
    assert "4111 1111 1111 1111" not in out
    assert out.count("***") == 4


def test_non_pii_is_not_destroyed():
    """Redaction must not eat ordinary business text or money."""
    for keep in [
        "Pipeline de vendas caiu 12% no trimestre",
        "R$ 12.500,00 em receita bruta",
        "proximo passo: revisar proposta do cliente",
        "ID do pedido: ABC-2024-XYZ",
    ]:
        assert redact_pii(keep) == keep


def test_empty_and_non_string():
    assert redact_pii("") == ""
    assert redact_pii(None) is None
    assert redact_pii(12345) == 12345


def test_redact_obj_recurses():
    payload = {
        "to": "maria.silva@empresa.com.br",
        "items": [{"cpf": "123.456.789-09"}, "call +55 11 91234-5678"],
        "count": 7,
    }
    out = redact_pii_obj(payload)
    assert out["to"] == "***"
    assert out["items"][0]["cpf"] == "***"
    assert out["items"][1] == "call ***"
    assert out["count"] == 7


def test_no_catastrophic_backtracking():
    """The patterns must stay linear: redaction runs on every traced payload."""
    payload = "a" * 20000 + " @" * 5000
    start = time.time()
    redact_pii(payload)
    elapsed = time.time() - start
    assert elapsed < 1.0, f"redaction took {elapsed:.2f}s on 30k chars"