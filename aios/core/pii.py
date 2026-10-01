"""PII auto-redaction — CPF, RG, cartão, telefone -> ***.

Regex sem catastrophic backtracking: todos padrões com quantificadores limitados e sem aninhamento.
"""
import re

# Cada padrão linear, sem grupos aninhados + quantificadores
_EMAIL = r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
_CPF_FMT = r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"
_CPF_11 = r"\b\d{11}\b"
_RG = r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[0-9Xx]\b"
# 13, 15, 16 e 19 dígitos; separadores distintos de espaço e hífen, que é como
# o cartão costuma ser ditado ("1234-5678-9012-3456").
_CARD = (
    r"\b(?:\d[ -]?){12}\d\b"
    r"|\b3[47]\d{2}[ -]?\d{6}[ -]?\d{5}\b"
    r"|\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"
    r"|\b\d{4}[ -]?\d{6}[ -]?\d{5}[ -]?\d{4}\b"
)
_PHONE = r"\(\d{2}\)\s?\d{4,5}-\d{4}\b"
# Celular com código do país: "+55 11 91234-5678" e "+5511987654321".
_PHONE_INTL = r"\+\d{1,3}[\s-]?\(?\d{2}\)?[\s-]?\d{4,5}[\s-]?\d{4}\b"
_CEP = r"\b\d{5}-\d{3}\b"
# Chaves de API/credencial que aparecem em logs de integração.
_TOKEN = (
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}"
    r"|sk_(?:live|test)_[A-Za-z0-9]{16,}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|AIza[A-Za-z0-9_\-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,})\b"
)

# Ordem: padrões mais longos/específicos primeiro
_COMBINED = re.compile(
    "|".join([
        _EMAIL, _TOKEN, _PHONE_INTL, _CARD, _CPF_FMT, _PHONE, _CEP, _RG, _CPF_11,
    ])
)

# Expõe individuais se necessário
CPF_FMT_RE = re.compile(_CPF_FMT)
CPF_11_RE = re.compile(_CPF_11)
RG_RE = re.compile(_RG)
CARD_RE = re.compile(_CARD)
PHONE_RE = re.compile(_PHONE)
EMAIL_RE = re.compile(_EMAIL)
TOKEN_RE = re.compile(_TOKEN)
PII_RE = _COMBINED


def redact_pii(text: str) -> str:
    """Substitui PII por ***. Não quebra se text não for str."""
    if not isinstance(text, str):
        return text  # type: ignore
    if not text:
        return text
    return _COMBINED.sub("***", text)


def redact_pii_obj(obj):
    """Redact recursivo para dict/list/str — uso interno tracing."""
    if isinstance(obj, str):
        return redact_pii(obj)
    if isinstance(obj, dict):
        return {k: redact_pii_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact_pii_obj(v) for v in obj)
    return obj
