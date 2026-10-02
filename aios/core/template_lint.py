"""Deterministic pre-submission linter for WhatsApp message templates.

Pure functions. No network, no LLM, no I/O. Every rule is transcribed from Meta's
published rejection guidance, which is the point: the linter raises first-pass
approval odds because it applies known rules exactly, whereas a model would
guess at what Meta's reviewer wants.

Two rules here cannot be obtained from Meta at all:

* duplication — submitting a body/footer identical to an existing template is
  rejected, but "duplicate" is NOT in Meta's rejected_reason enum, so only a
  local check can catch it;
* sensitive-identifier and phrasing policy checks, which Meta applies by human
  or ML review with no published signal.

Findings carry a severity so callers can gate submission: submit requires zero
``error`` findings. ``warning`` findings are advisory and never block.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# --- Meta constraints -----------------------------------------------------

NAME_RE = re.compile(r"^[a-z0-9_]+$")
NAME_MAX = 512
FOOTER_MAX_CHARS = 60

# {{1}} style placeholders
PARAM_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
BRACE_RE = re.compile(r"\{\{|\}\}")
# Marketing/utility wording that tends to trip policy review.
SENSITIVE_PATTERNS = (
    (re.compile(r"\b\d{13,19}\b"), "looks like a full payment card number"),
    (re.compile(r"\b\d{11}\b"), "looks like a Brazilian CPF or full national ID"),
    (re.compile(r"\b(?:cpf|cnpj|rg|ssn|passport|senha|password)\b", re.I),
     "asks for a sensitive identifier or credential"),
    (re.compile(r"\b(?:pix|transfer(?:ir|e)?|deposit|depositar|transferir)\b.{0,40}\b(?:dinheiro|real|valor|pagamento|reais)\b", re.I),
     "asks the user to transfer money"),
    (re.compile(r"\b(?:process\w*|juiz\w*|advogad\w*|multa\w*|indeniza\w*|calde[aã]o\w*|denunci\w*|cobra(?:ndo|do|da)?)\b.{0,80}", re.I),
     "threatening legal action, collection or public exposure"),
    (re.compile(r"\b(?:falta de pagamento|inadimplente|negativad[oa]|sera distrit[oa]|pode ser processad[oa])\b", re.I),
     "threatens debt collection or legal action"),
    (re.compile(r"\b(?:ganhe|ganha|ganhando|oferta imperdível|última chance|por tempo limitado|compre agora|desconto imperdível)\b", re.I),
     "promotional phrasing that is rejected in the UTILITY category"),
)
FORMATTING_RE = re.compile(r"[*_~`]|</?\w+>")


@dataclass
class Finding:
    severity: str          # "error" | "warning"
    rule_id: str
    message: str
    field: str = "body"   # which part of the template
    span: tuple | None = None

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "rule_id": self.rule_id,
            "message": self.message,
            "field": self.field,
            "span": list(self.span) if self.span else None,
        }


@dataclass
class TemplateDraft:
    name: str = ""
    language: str = "pt_BR"
    category: str = "UTILITY"
    header_text: str = ""
    body: str = ""
    footer: str = ""
    examples: dict = field(default_factory=dict)
    existing_bodies: list = field(default_factory=list)


# --- individual rules -----------------------------------------------------

def _check_name(draft: TemplateDraft, out: list) -> None:
    name = (draft.name or "").strip()
    if not name:
        out.append(Finding("error", "name.required", "Template name is required", "name"))
        return
    if not NAME_RE.match(name):
        out.append(Finding(
            "error", "name.charset",
            "Name may only contain lowercase letters, digits and underscores (a-z0-9_).",
            "name",
        ))
    if len(name) > NAME_MAX:
        out.append(Finding("error", "name.too_long", f"Name exceeds {NAME_MAX} characters.", "name"))


def _params(text: str) -> list[int]:
    return [int(m.group(1)) for m in PARAM_RE.finditer(text or "")]


def _check_sequential(draft: TemplateDraft, out: list, where: str, text: str) -> None:
    nums = _params(text)
    if not nums:
        return
    expected = list(range(1, len(nums) + 1))
    if nums != expected:
        # find first divergence for a precise message
        for i, (got, want) in enumerate(zip(nums, expected)):
            if got != want:
                out.append(Finding(
                    "error", "params.sequence",
                    f"Parameters must be sequential starting at {{{{1}}}}; "
                    f"position {i + 1} uses {{{{{got}}}}} where {{{{{want}}}}} was expected.",
                    where,
                ))
                return
        out.append(Finding("error", "params.sequence", "Parameters must be sequential starting at {{1}}.", where))


def _check_braces(text: str, where: str, out: list) -> None:
    """Catch both unbalanced {{ }} and stray single braces.

    Counting "{{" against "}}" was not enough: "sua consulta {2}" has one of each
    and passed, even though {2} is a malformed parameter.
    """
    if not text:
        return
    # remove every well-formed {{n}} then look for leftover braces
    leftover = PARAM_RE.sub("", text)
    if "{{" in leftover or "}}" in leftover or "{" in leftover or "}" in leftover:
        out.append(Finding(
            "error", "params.braces",
            "Malformed variable. The correct format is {{1}} — two braces each side.",
            where,
        ))


def _check_dangling(draft: TemplateDraft, out: list) -> None:
    raw = draft.body or ""
    body = raw.strip()
    if not body:
        return
    # Spans must be offsets into the ORIGINAL text the user typed. An earlier
    # version computed them against the stripped copy, so the editor highlighted
    # the wrong characters whenever the body had leading or trailing whitespace.
    offset = len(raw) - len(raw.lstrip())
    # first non-space token must not be a bare parameter
    first = PARAM_RE.match(body)
    if first:
        out.append(Finding(
            "error", "params.dangling",
            "A template must not start with a parameter. Add text before {{1}} so it is "
            "clear what will be inserted.",
            "body", (offset, offset + first.end()),
        ))
    last = None
    for m in PARAM_RE.finditer(body):
        last = m
    if last and body[last.end():].strip() == "":
        out.append(Finding(
            "error", "params.dangling",
            "A template must not end with a parameter. Add text after it.",
            "body", (offset + last.start(), offset + last.end()),
        ))


def _check_floating(draft: TemplateDraft, out: list) -> None:
    for i, line in enumerate((draft.body or "").splitlines() or []):
        stripped = line.strip()
        if not stripped:
            continue
        without = PARAM_RE.sub("", stripped).strip()
        if stripped != without and without == "":
            out.append(Finding(
                "error", "params.floating",
                "A line consisting only of parameters is rejected. Surround each variable "
                "with text so the reader knows what goes there.",
                "body",
            ))


def _check_footer(draft: TemplateDraft, out: list) -> None:
    footer = (draft.footer or "").strip()
    if not footer:
        return
    if PARAM_RE.search(footer) or "{{" in footer:
        out.append(Finding("error", "footer.no_params", "The footer must not contain variables.", "footer"))
    if FORMATTING_RE.search(footer):
        out.append(Finding("error", "footer.formatting", "The footer must not contain bold/italic formatting.", "footer"))
    if len(footer) > FOOTER_MAX_CHARS:
        out.append(Finding(
            "error", "footer.too_long",
            f"The footer must be {FOOTER_MAX_CHARS} characters or fewer (is {len(footer)}).",
            "footer",
        ))


def _check_header(draft: TemplateDraft, out: list) -> None:
    header = (draft.header_text or "").strip()
    if not header:
        return
    if FORMATTING_RE.search(header):
        out.append(Finding("error", "header.formatting", "The header must not contain bold/italic formatting.", "header_text"))
    _check_sequential(draft, out, "header_text", header)
    _check_braces(header, "header_text", out)


def _check_examples(draft: TemplateDraft, out: list) -> None:
    """Meta requires an example value for every parameter at creation time."""
    needed = set()
    for text in (draft.header_text or "", draft.body or "", draft.footer or ""):
        needed.update(_params(text))
    examples = draft.examples or {}
    for n in sorted(needed):
        if not str(examples.get(str(n), "")).strip():
            out.append(Finding(
                "error", "params.example_missing",
                f"Parameter {{{{{n}}}}} needs an example value. Meta rejects templates with "
                "parameters that have no example.",
                "examples",
            ))


def _check_ratio(draft: TemplateDraft, out: list) -> None:
    """Heuristic from Meta's guidance: too many variables relative to text."""
    body = (draft.body or "")
    nums = _params(body)
    if not nums:
        return
    static_words = len(PARAM_RE.sub(" ", body).split())
    needed = 3 * len(nums) + 1
    if static_words < needed:
        out.append(Finding(
            "warning", "params.ratio",
            f"{len(nums)} variable(s) with only {static_words} static word(s). Meta commonly "
            f"rejects templates with too few words per variable; aim for at least {needed}.",
            "body",
        ))


def _check_policy(draft: TemplateDraft, out: list) -> None:
    for where, text in (("header_text", draft.header_text), ("body", draft.body), ("footer", draft.footer)):
        for rx, why in SENSITIVE_PATTERNS:
            m = rx.search(text or "")
            if m:
                sev = "error" if where == "body" else "warning"
                out.append(Finding(sev, "policy.sensitive", f"Content {why}.", where, (m.start(), m.end())))


def _check_category(draft: TemplateDraft, out: list) -> None:
    """UTILITY templates get rejected for promotional wording."""
    if (draft.category or "").upper() != "UTILITY":
        return
    text = " ".join(filter(None, [draft.body, draft.footer, draft.header_text]))
    promo = re.search(r"\b(?:promo[cç][aã]o|desconto|black friday|oferta|liquida[cç][aã]o| Imperd[ií]vel|compre agora)\b", text, re.I)
    if promo:
        out.append(Finding(
            "error", "category.mismatch",
            "Promotional wording in a UTILITY template is a common rejection cause. Either "
            "reword it as a factual notification, or set the category to MARKETING.",
            "body",
        ))


def _check_duplicate(draft: TemplateDraft, out: list) -> None:
    """Not obtainable from Meta: duplicate body+footer is rejected silently."""
    def norm(s: str) -> str:
        # Normalise accents rather than deleting them. Stripping "ol\u00e1" down to
        # "ol" made "ol\u00e1" and "ola" different templates, so the duplicate check
        # silently never matched Portuguese text -- the primary language here.
        s = PARAM_RE.sub("{{}}", s or "")
        s = unicodedata.normalize("NFKD", s.lower())
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        s = re.sub(r"[^a-z0-9{}\s]", "", s)
        return re.sub(r"\s+", " ", s).strip()

    # Normalise both sides identically. An earlier version appended "|"+footer to
    # the draft side only, so the comparison could never match.
    if not norm(draft.body):
        return
    mine = norm(draft.body)
    for other in draft.existing_bodies or []:
        if not isinstance(other, str):
            continue
        if mine == norm(other):
            out.append(Finding(
                "error", "duplicate.content",
                "This body and footer match an existing template. Meta rejects duplicates, and "
                "it does not report duplication in rejected_reason — this is caught locally.",
                "body",
            ))
            return


# --- entry point ----------------------------------------------------------

def lint_template(draft: TemplateDraft) -> list:
    """Return findings. Empty list (of errors) means safe to submit."""
    out: list = []
    _check_name(draft, out)
    _check_braces(draft.body or "", "body", out)
    _check_sequential(draft, out, "body", draft.body or "")
    _check_dangling(draft, out)
    _check_floating(draft, out)
    _check_footer(draft, out)
    _check_header(draft, out)
    _check_examples(draft, out)
    _check_ratio(draft, out)
    _check_policy(draft, out)
    _check_category(draft, out)
    _check_duplicate(draft, out)
    if not (draft.body or "").strip():
        out.append(Finding("error", "body.required", "Template body is required.", "body"))
    return out


def errors(findings: list) -> list:
    return [f for f in findings if f.severity == "error"]


def warnings(findings: list) -> list:
    return [f for f in findings if f.severity == "warning"]


def can_submit(findings: list) -> bool:
    return not errors(findings)


def summarise(findings: list) -> str:
    """One-line human summary. Never invents a reason Meta did not give."""
    e, w = errors(findings), warnings(findings)
    if not e and not w:
        return "Pronto para envio: nenhuma regraautomatica foi violada. A aprovação final é do Meta."
    parts = []
    if e:
        parts.append(f"{len(e)} erro(s)")
    if w:
        parts.append(f"{len(w)} aviso(s)")
    return f"{' e '.join(parts)}. Meta faz a revisão final e pode rejeitar por motivos que não são verificáveis localmente."