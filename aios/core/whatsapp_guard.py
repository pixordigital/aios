import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

OPT_OUT_KEYWORDS = {"sair", "stop", "cancelar", "parar", "descadastrar", "unsubscribe", "opt out"}
OPT_IN_KEYWORDS = {"sim", "aceito", "quero", "opt in"}

_contact_queues: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
_opt_out: set[str] = set()
_opt_in: set[str] = set()


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


def can_send(contact: str, now: float | None = None) -> tuple[bool, str]:
    if check_opt_out(contact):
        return False, "opt-out"
    now = now or time.time()
    q = _contact_queues[contact]
    q = deque([t for t in q if now - t < 3600], maxlen=100)
    _contact_queues[contact] = q
    if len([t for t in q if now - t < 60]) >= 3:
        return False, "rate 3/min"
    if len(q) >= 10:
        return False, "rate 10/h"
    daily = [t for t in q if now - t < 86400]
    if len(daily) >= 50:
        return False, "rate 50/d"
    return True, ""


def record_send(contact: str):
    _contact_queues[contact].append(time.time())


async def guard_send(contact: str, text: str, is_template: bool = False, window_open: bool = True) -> tuple[bool, str]:
    if is_opt_out(text):
        record_opt_out(contact)
        return False, "user opt-out recorded"
    if not window_open and not is_template:
        return False, "fora da janela 24h exige template"
    ok, reason = can_send(contact)
    if not ok:
        logger.warning("WhatsApp guard block %s: %s", contact, reason)
        return False, reason
    record_send(contact)
    return True, ""


def human_handover_needed(text: str) -> bool:
    return any(k in text.lower() for k in ["humano", "pessoa", "atendente", "falar com alguém"])
