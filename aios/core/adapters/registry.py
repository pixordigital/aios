"""Business execution adapter registry/factory (fail-closed, live-safe slice)."""

from __future__ import annotations

from typing import Any, Callable

from aios.core.adapters.calendar_calcom import CalComAdapter
from aios.core.adapters.calendar_google import GoogleCalendarAdapter
from aios.core.adapters.crm_internal import CrmInternalAdapter
from aios.core.adapters.email_resend import ResendEmailAdapter
from aios.core.adapters.fulfillment_service import ServiceFulfillmentAdapter
from aios.core.adapters.whatsapp_evolution import EvolutionWhatsAppAdapter
from aios.core.business_execution import ExecutionRegistry

AuditCallback = Callable[[dict[str, Any]], None]


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {v.strip() for v in value.split(",") if v.strip()}
    try:
        return {str(v).strip() for v in value if str(v).strip()}
    except TypeError:
        return set()


def _approved_set(approved_adapters: Any, settings: Any) -> set[str]:
    approved = _as_set(approved_adapters)
    if settings is not None:
        approved |= _as_set(getattr(settings, "approved_adapters", None))
        approved |= _as_set(getattr(settings, "execution_approved_adapters", None))
    return approved


def _config_flag(name: str, settings: Any) -> bool:
    if settings is None:
        return False
    for attr in (f"{name}_approved", f"adapter_{name}_approved", f"approved_{name}"):
        if bool(getattr(settings, attr, False)):
            return True
    # Common env-style settings fields
    upper = name.upper()
    for attr in (f"{upper}_APPROVED", f"ADAPTER_{upper}_APPROVED"):
        if bool(getattr(settings, attr, False)):
            return True
    return False


def _is_approved(name: str, *, approved: set[str], settings: Any) -> bool:
    return name in approved or _config_flag(name, settings)


def _cfg(settings: Any, *names: str, default: Any = None) -> Any:
    if settings is None:
        return default
    for name in names:
        val = getattr(settings, name, None)
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        return val
    return default


def build_business_execution_registry(
    *,
    settings: Any = None,
    db: Any = None,
    audit_callback: AuditCallback | None = None,
    sandbox_senders: dict[str, Any] | None = None,
    approved_adapters: Any = None,
) -> ExecutionRegistry:
    """Build fail-closed registry for live-safe business execution slice.

    Adapters registered: crm_internal, whatsapp_evolution, email_resend,
    calendar_calcom (primary), calendar_google (optional), fulfillment_service.

    Approval is explicit: only adapters named in approved_adapters/config flags
    are marked approved. Missing config keeps adapters unapproved/fail-closed.
    sandbox_senders injects test/sandbox senders/clients/handlers by adapter name.
    """
    senders = dict(sandbox_senders or {})
    approved = _approved_set(approved_adapters, settings)
    registry = ExecutionRegistry(audit_callback=audit_callback)

    # CRM internal - uses internal DB, no external creds; config = db present.
    crm_name = "crm_internal"
    crm_approved = _is_approved(crm_name, approved=approved, settings=settings) and db is not None
    registry.register(
        CrmInternalAdapter(
            db=db,
            approved=crm_approved,
            audit_callback=audit_callback,
        )
    )

    # WhatsApp Evolution - sandbox sender injectable; config = url+key.
    wa_name = "whatsapp_evolution"
    wa_sender = senders.get(wa_name, senders.get("whatsapp"))
    wa_url = _cfg(settings, "evolution_server_url", "EVOLUTION_SERVER_URL")
    wa_key = _cfg(settings, "evolution_api_key", "EVOLUTION_API_KEY")
    # Sandbox injection may provide explicit config; dummy config only when sender+approved.
    wa_requested = _is_approved(wa_name, approved=approved, settings=settings)
    wa_cfg = dict(senders.get(f"{wa_name}_config") or {})
    if wa_sender is not None and wa_requested:
        wa_url = wa_url or wa_cfg.get("server_url") or "https://sandbox.evolution.local"
        wa_key = wa_key or wa_cfg.get("api_key") or "sandbox-key"
    wa_configured = bool(str(wa_url or "").strip() and str(wa_key or "").strip())
    wa_approved = wa_requested and wa_configured
    registry.register(
        EvolutionWhatsAppAdapter(
            approved=wa_approved,
            server_url=str(wa_url).strip() if wa_url else None,
            api_key=str(wa_key).strip() if wa_key else None,
            sender=wa_sender,
            audit_callback=audit_callback,
        )
    )

    # Email Resend - sandbox sender injectable; config = api key + from.
    email_name = "email_resend"
    email_sender = senders.get(email_name, senders.get("email"))
    email_cfg = {
        "RESEND_API_KEY": _cfg(settings, "resend_api_key", "RESEND_API_KEY"),
        "from": _cfg(settings, "resend_from_email", "RESEND_FROM_EMAIL", "email_from"),
    }
    email_cfg.update(dict(senders.get(f"{email_name}_config") or {}))
    email_requested = _is_approved(email_name, approved=approved, settings=settings)
    if email_sender is not None and email_requested:
        email_cfg["RESEND_API_KEY"] = email_cfg.get("RESEND_API_KEY") or "sandbox-resend-key"
        email_cfg["from"] = email_cfg.get("from") or "sandbox@aios.local"
    email_configured = bool(
        str(email_cfg.get("RESEND_API_KEY") or "").strip() and str(email_cfg.get("from") or "").strip()
    )
    email_approved = email_requested and email_configured
    registry.register(
        ResendEmailAdapter(
            approved=email_approved,
            config={k: v for k, v in email_cfg.items() if v is not None},
            sender=email_sender,
        )
    )

    # Cal.com primary calendar - sandbox client injectable.
    cal_name = "calendar_calcom"
    cal_sender = senders.get(cal_name) or senders.get("calcom") or senders.get("calendar_calcom_client")
    cal_api_key = _cfg(settings, "calcom_api_key", "CALCOM_API_KEY")
    cal_event_type = _cfg(settings, "calcom_event_type", "CALCOM_EVENT_TYPE")
    cal_webhook = _cfg(settings, "calcom_webhook_secret", "CALCOM_WEBHOOK_SECRET")
    cal_cfg = dict(senders.get(f"{cal_name}_config") or {})
    cal_requested = _is_approved(cal_name, approved=approved, settings=settings)
    if cal_sender is not None and cal_requested:
        cal_api_key = cal_api_key or cal_cfg.get("api_key") or "sandbox-cal-key"
        cal_event_type = cal_event_type or cal_cfg.get("event_type") or "sandbox-event"
        cal_webhook = cal_webhook or cal_cfg.get("webhook_secret") or "sandbox-webhook"
    cal_configured = bool(cal_api_key and cal_event_type and cal_webhook)
    cal_approved = cal_requested and cal_configured
    cal_adapter = CalComAdapter(
        api_key=str(cal_api_key).strip() if cal_api_key else None,
        event_type=str(cal_event_type).strip() if cal_event_type else None,
        webhook_secret=str(cal_webhook).strip() if cal_webhook else None,
        client=cal_sender,
        approved=cal_approved,
    )
    cal_adapter.name = cal_name  # registry identity; class default is "calcom"
    registry.register(cal_adapter)

    # Google Calendar optional - sandbox client injectable.
    gcal_name = "calendar_google"
    gcal_sender = senders.get(gcal_name) or senders.get("google_calendar") or senders.get("calendar_google_client")
    gcal_creds = _cfg(settings, "google_calendar_credentials", "GOOGLE_CALENDAR_CREDENTIALS")
    gcal_calendar_id = _cfg(settings, "google_calendar_id", "GOOGLE_CALENDAR_ID")
    gcal_cfg = dict(senders.get(f"{gcal_name}_config") or {})
    gcal_requested = _is_approved(gcal_name, approved=approved, settings=settings)
    if gcal_sender is not None and gcal_requested:
        gcal_creds = gcal_creds or gcal_cfg.get("credentials") or {"sandbox": True}
        gcal_calendar_id = gcal_calendar_id or gcal_cfg.get("calendar_id") or "sandbox"
    gcal_configured = bool(gcal_creds) and bool(str(gcal_calendar_id or "").strip())
    gcal_approved = gcal_requested and gcal_configured
    gcal_adapter = GoogleCalendarAdapter(
        credentials=gcal_creds,
        calendar_id=str(gcal_calendar_id).strip() if gcal_calendar_id else None,
        client=gcal_sender,
        approved=gcal_approved,
    )
    gcal_adapter.name = gcal_name
    registry.register(gcal_adapter)

    # Fulfillment service - generic, sandbox handler injectable.
    ff_name = "fulfillment_service"
    ff_handler = senders.get(ff_name) or senders.get("fulfillment") or senders.get("fulfillment_handler")
    ff_cfg = dict(senders.get(f"{ff_name}_config") or {})
    ff_steps = ff_cfg.get("steps") or _cfg(settings, "fulfillment_steps", default=None) or [{"name": "default"}]
    ff_requested = _is_approved(ff_name, approved=approved, settings=settings)
    ff_configured = bool(ff_handler is not None and ff_steps)
    ff_approved = ff_requested and ff_configured
    registry.register(
        ServiceFulfillmentAdapter(
            approved=ff_approved,
            configured=ff_configured,
            steps=list(ff_steps),
            sandbox_handler=ff_handler,
            audit_callback=audit_callback,
        )
    )

    return registry
