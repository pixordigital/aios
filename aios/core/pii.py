"""PII auto-redaction — CPF, RG, cartão, telefone -> ***.

Regex sem catastrophic backtracking: todos padrões com quantificadores limitados e sem aninhamento.
"""
import re

# Cada padrão linear, sem grupos aninhados + quantificadores
_CPF_FMT = r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"
_CPF_11 = r"\b\d{11}\b"
_RG = r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[0-9Xx]\b"
_CARD = r"\b\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}\b"
_PHONE = r"\(\d{2}\)\s?\d{4,5}-\d{4}\b"

# Ordem: padrões mais longos/específicos primeiro
_COMBINED = re.compile(
    "|".join([_CPF_FMT, _CARD, _PHONE, _RG, _CPF_11])
)

# Expõe individuais se necessário
CPF_FMT_RE = re.compile(_CPF_FMT)
CPF_11_RE = re.compile(_CPF_11)
RG_RE = re.compile(_RG)
CARD_RE = re.compile(_CARD)
PHONE_RE = re.compile(_PHONE)
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
