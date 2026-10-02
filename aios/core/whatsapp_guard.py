import logging
import time
from collections import OrderedDict, defaultdict, deque

logger = logging.getLogger(__name__)

OPT_OUT_KEYWORDS = {"sair", "stop", "cancelar", "parar", "descadastrar", "unsubscribe", "opt out"}
OPT_IN_KEYWORDS = {"sim", "aceito", "quero", "opt in"}

_contact_queues: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
_opt_out: set[str] = set()
_opt_in: set[str] = set()
# These were unbounded: one permanent entry per unique phone number, plus a
# plain list per number with no maxlen (unlike the sibling _contact_queues, which
# correctly caps at 100). At tens of thousands of leads that is a slow leak in a
# 1536MB container. Cap both.
_GUARD_MAX_CONTACTS = 20000
_last_text: "OrderedDict[str, tuple[str, float]]" = OrderedDict()
_last_numbers: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))


def _remember_contact(key: str) -> None:
    """Track LRU access and evict the oldest contact past the cap."""
    _last_text[key] = _last_text.pop(key, (0.0, 0.0))
    while len(_last_text) > _GUARD_MAX_CONTACTS:
        _last_text.popitem(last=False)


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


# --- durable state ---
# The in-memory sets above are the fast path. These mirror them into the
# database so a deploy does not resurrect contacts that already opted out.
# Everything degrades to no-op when there is no DB session (unit tests, CLI).

async def persist_opt_out(org_id: str, contact: str, reason: str = "user request"):
    _opt_out.add(contact)
    _opt_in.discard(contact)
    await _store_contact(org_id, contact, "opted_out", reason, None)


async def persist_opt_in(org_id: str, contact: str):
    _opt_in.add(contact)
    _opt_out.discard(contact)
    await _store_contact(org_id, contact, "active", "", None)


async def persist_cooldown(org_id: str, contact: str, minutes: int, reason: str = "ban signal"):
    until = time.time() + minutes * 60
    _blocked_until[contact] = until
    import datetime

    await _store_contact(
        org_id, contact, "cooldown", reason,
        datetime.datetime.utcfromtimestamp(until),
    )


async def _store_contact(org_id: str, contact: str, state: str, reason: str, until):
    if not org_id:
        return
    try:
        from sqlalchemy import select as sql_select

        from aios.db.backend import db_session
        from aios.db.models import WhatsappContact

        async with db_session() as db:
            row = (await db.execute(
                sql_select(WhatsappContact).where(
                    WhatsappContact.org_id == org_id,
                    WhatsappContact.number == contact,
                )
            )).scalar_one_or_none()
            if row is None:
                row = WhatsappContact(org_id=org_id, number=contact)
                db.add(row)
            row.state = state
            row.reason = reason[:64]
            row.until = until
            await db.commit()
    except Exception:
        logger.debug("whatsapp guard: could not persist %s for %s", state, contact)


async def load_durable_state(org_id: str):
    """Rehydrate opt-outs and live cooldowns at startup.

    Called once per process boot. Without this every restart forgets who opted
    out, which is both a ban risk and an LGPD problem.
    """
    if not org_id:
        return {"opted_out": 0, "cooldown": 0}
    try:
        from sqlalchemy import select as sql_select

        from aios.db.backend import db_session
        from aios.db.models import WhatsappContact

        counts = {"opted_out": 0, "cooldown": 0}
        now = time.time()
        async with db_session() as db:
            rows = (await db.execute(
                sql_select(WhatsappContact).where(WhatsappContact.org_id == org_id)
            )).scalars().all()
        for r in rows:
            if r.state == "opted_out":
                _opt_out.add(r.number)
                counts["opted_out"] += 1
            elif r.state == "cooldown" and r.until is not None:
                # coerce naive/aware datetimes without dragging in a tz lib
                ts = r.until.replace(tzinfo=__import__("datetime").timezone.utc).timestamp()
                if ts > now:
                    _blocked_until[r.number] = ts
                    counts["cooldown"] += 1
        if counts["opted_out"] or counts["cooldown"]:
            logger.info(
                "whatsapp guard: rehydrated %d opt-outs, %d cooldowns",
                counts["opted_out"], counts["cooldown"],
            )
        return counts
    except Exception:
        logger.debug("whatsapp guard: could not load durable state")
        return {"opted_out": 0, "cooldown": 0}


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
    contact: str,
    text: str,
    is_template: bool = False,
    window_open: bool = True,
    provider: str = "meta",
    instance: str = "",
    record: bool = True,
) -> tuple[bool, str]:
    """Decide whether a send may proceed.

    Exactly one caller per outbound message must pass `record=True` — the
    layer that owns the send. Every other layer on the path (the delivery
    retry wrapper) passes `record=False` for a pure pre-check.

    The distinction is load-bearing: this function writes `_last_text`,
    `record_send` and `record_global_send`, and the very next line reads
    `_last_text` back through `is_duplicate`. Two recording calls for one
    message meant the second one always saw its own write and returned
    "duplicate 5min", so the send was refused *after* it had been approved —
    every agent reply was dropped and retried into the DLQ.
    """
    if is_opt_out(text):
        record_opt_out(contact)
        return False, "user opt-out recorded"
    if not window_open and not is_template and provider == "meta":
        return False, "fora da janela 24h exige template"
    # AIOS diferencial: responde 24/7 independente do horário — sem bloqueio por horário
    # is_allowed_hour() mantido apenas para métrica/SLA, não para bloquear envio
    # if not is_allowed_hour() and provider == "evolution":
    #     return False, "fora do horário 8-20"
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
    if not record:
        return True, ""
    record_send(contact)
    record_global_send(instance)
    _last_text[contact] = (text.strip(), time.time())
    _remember_contact(contact)  # LRU touch + eviction past the cap
    return True, ""


def human_handover_needed(text: str) -> bool:
    return any(k in text.lower() for k in ["humano", "pessoa", "atendente", "falar com alguém"])
