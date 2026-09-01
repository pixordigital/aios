import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

OPT_OUT_KEYWORDS = {"sair", "stop", "cancelar", "parar", "descadastrar", "unsubscribe", "opt out"}
OPT_IN_KEYWORDS = {"sim", "aceito", "quero", "opt in"}

_contact_queues: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
_opt_out: set[str] = set()
_opt_in: set[str] = set()
_last_text: dict[str, tuple[str, float]] = {}
_last_numbers: dict[str, list[str]] = defaultdict(list)


def is_opt_out(text: str) -> bool:
    return text.strip().lower() in OPT_OUT_KEYWORDS


def is_opt_in(text: str) -> bool:
    return text.strip().lower() in OPT_IN_KEYWORDS


def check_opt_out(contact: str) -> bool:
    return contact in _opt_out


def record_opt_out(contact: str):
    _opt_out.add(contact)
    _opt_in.discard(contact)


def record_opt_in(contact: str):
    _opt_in.add(contact)
    _opt_out.discard(contact)


def can_send(contact: str, now: float | None = None, provider: str = "meta") -> tuple[bool, str]:
    if check_opt_out(contact):
        return False, "opt-out"
    now = now or time.time()
    q = _contact_queues[contact]
    q = deque([t for t in q if now - t < 3600], maxlen=100)
    _contact_queues[contact] = q
    if provider == "evolution":
        if len([t for t in q if now - t < 60]) >= 1:
            return False, "evolution 1/min"
        if len(q) >= 5:
            return False, "evolution 5/h"
        if len([t for t in q if now - t < 86400]) >= 20:
            return False, "evolution 20/d warmup"
    else:
        if len([t for t in q if now - t < 60]) >= 3:
            return False, "rate 3/min"
        if len(q) >= 10:
            return False, "rate 10/h"
        if len([t for t in q if now - t < 86400]) >= 50:
            return False, "rate 50/d"
    return True, ""


def is_duplicate(contact: str, text: str, window: int = 300) -> bool:
    last, ts = _last_text.get(contact, ("", 0))
    if text.strip() == last and time.time() - ts < window:
        return True
    return False


def humanize_delay(text: str) -> float:
    import random

    base = min(len(text) * 0.04, 3.0)
    return round(random.uniform(1.5 + base, 3.0 + base), 2)


def has_spam_signals(text: str) -> str | None:
    if text.count("http") > 2:
        return "many links"
    if len(text) > 1000 and text.count("\n") < 2:
        return "long block"
    if text.upper() == text and len(text) > 20:
        return "caps"
    return None


def record_send(contact: str):
    _contact_queues[contact].append(time.time())


async def guard_send(
    contact: str, text: str, is_template: bool = False, window_open: bool = True, provider: str = "meta"
) -> tuple[bool, str]:
    if is_opt_out(text):
        record_opt_out(contact)
        return False, "user opt-out recorded"
    if not window_open and not is_template and provider == "meta":
        return False, "fora da janela 24h exige template"
    if is_duplicate(contact, text):
        return False, "duplicate 5min"
    spam = has_spam_signals(text)
    if spam:
        logger.warning("Spam signal %s for %s", spam, contact)
    ok, reason = can_send(contact, provider=provider)
    if not ok:
        logger.warning("WhatsApp guard block %s [%s]: %s", contact, provider, reason)
        return False, reason
    record_send(contact)
    _last_text[contact] = (text.strip(), time.time())
    return True, ""


def human_handover_needed(text: str) -> bool:
    return any(k in text.lower() for k in ["humano", "pessoa", "atendente", "falar com alguém"])
