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


_global_daily: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
_instance_created: dict[str, float] = {}
_blocked_until: dict[str, float] = {}

def set_instance_warmup(instance: str, created_at: float | None = None):
    if created_at:
        _instance_created[instance] = created_at

def _warmup_limits(instance: str, now: float) -> tuple[int, int, int]:
    created = _instance_created.get(instance, 0)
    age_days = (now - created) / 86400 if created else 999
    if age_days < 7:
        return 1, 3, 15
    if age_days < 14:
        return 1, 5, 30
    if age_days < 30:
        return 2, 8, 40
    return 2, 10, 60

def _global_quota(instance: str, now: float) -> tuple[bool, str]:
    if not instance:
        return True, ""
    dq = _global_daily[instance]
    dq = deque([t for t in dq if now - t < 86400], maxlen=500)
    _global_daily[instance] = dq
    _, _, daily = _warmup_limits(instance, now)
    if len(dq) >= daily:
        return False, f"global {daily}/d warmup"
    return True, ""

def can_send(contact: str, now: float | None = None, provider: str = "meta", instance: str = "") -> tuple[bool, str]:
    if check_opt_out(contact):
        return False, "opt-out"
    now = now or time.time()
    if _blocked_until.get(contact, 0) > now:
        return False, "cooldown"
    q = _contact_queues[contact]
    q = deque([t for t in q if now - t < 3600], maxlen=100)
    _contact_queues[contact] = q
    if provider == "evolution":
        per_min, per_hour, per_day = _warmup_limits(instance, now)
        if len([t for t in q if now - t < 60]) >= per_min:
            return False, f"evolution {per_min}/min"
        if len(q) >= per_hour:
            return False, f"evolution {per_hour}/h"
        if len([t for t in q if now - t < 86400]) >= per_day:
            return False, f"evolution {per_day}/d warmup"
        ok, reason = _global_quota(instance, now)
        if not ok:
            return False, reason
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


def is_allowed_hour(now: float | None = None, tz: str = "America/Sao_Paulo") -> bool:
    try:
        import datetime, zoneinfo
        dt = datetime.datetime.fromtimestamp(now or time.time(), tz=zoneinfo.ZoneInfo(tz))
        return 8 <= dt.hour < 20
    except Exception:
        import datetime
        return 8 <= datetime.datetime.now().hour < 20

def vary_text(text: str) -> str:
    import random
    variants = {
        "Olá": ["Olá", "Oi", "Olá!"],
        "obrigado": ["obrigado", "obrigado!", "muito obrigado"],
    }
    for k, vals in variants.items():
        if k.lower() in text.lower():
            text = text.replace(k, random.choice(vals), 1)
            break
    if random.random() < 0.15:
        text = text.rstrip() + random.choice([" 🙂", " 👍", ""])
    return text

def humanize_delay(text: str) -> float:
    import random
    base = min(len(text) * 0.045, 4.0)
    jitter = random.uniform(0.8, 2.2)
    return round(random.uniform(1.8 + base + jitter, 3.5 + base + jitter), 2)

def record_ban_signal(contact: str, minutes: int = 60):
    import time
    _blocked_until[contact] = time.time() + minutes * 60

def record_global_send(instance: str):
    if instance:
        _global_daily[instance].append(time.time())


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
    contact: str, text: str, is_template: bool = False, window_open: bool = True, provider: str = "meta", instance: str = ""
) -> tuple[bool, str]:
    if is_opt_out(text):
        record_opt_out(contact)
        return False, "user opt-out recorded"
    if not window_open and not is_template and provider == "meta":
        return False, "fora da janela 24h exige template"
    if not is_allowed_hour() and provider == "evolution":
        return False, "fora do horário 8-20"
    if is_duplicate(contact, text):
        return False, "duplicate 5min"
    spam = has_spam_signals(text)
    if spam:
        logger.warning("Spam signal %s for %s", spam, contact)
        if provider == "evolution":
            return False, f"spam {spam}"
    ok, reason = can_send(contact, provider=provider, instance=instance)
    if not ok:
        logger.warning("WhatsApp guard block %s [%s]: %s", contact, provider, reason)
        return False, reason
    record_send(contact)
    record_global_send(instance)
    _last_text[contact] = (text.strip(), time.time())
    return True, ""


def human_handover_needed(text: str) -> bool:
    return any(k in text.lower() for k in ["humano", "pessoa", "atendente", "falar com alguém"])
