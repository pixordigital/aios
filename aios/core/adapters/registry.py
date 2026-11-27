"""Business execution adapter registry/factory (fail-closed, live-safe slice)."""

from __future__ import annotations

from typing import Any, Callable

from aios.core.adapters.accounting_erp import AccountingErpAdapter
from aios.core.adapters.billing_stripe import StripeBillingAdapter
from aios.core.adapters.calendar_calcom import CalComAdapter
from aios.core.adapters.calendar_google import GoogleCalendarAdapter
from aios.core.adapters.contract_esign import ContractEsignAdapter
from aios.core.adapters.crm_internal import CrmInternalAdapter
from aios.core.adapters.email_resend import ResendEmailAdapter
from aios.core.adapters.fiscal_provider import FiscalProviderAdapter
from aios.core.adapters.fulfillment_service import ServiceFulfillmentAdapter
from aios.core.adapters.payroll_provider import PayrollProviderAdapter
from aios.core.adapters.tax_fiscal import TaxFiscalAdapter
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
    for attr in (
        f"{name}_approved",
        f"adapter_{name}_approved",
        f"approved_{name}",
        f"execution_adapter_{name}_approved",
    ):
        if bool(getattr(settings, attr, False)):
            return True
    # Common env-style settings fields
    upper = name.upper()
    for attr in (
        f"{upper}_APPROVED",
        f"ADAPTER_{upper}_APPROVED",
        f"EXECUTION_ADAPTER_{upper}_APPROVED",
    ):
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
    idempotency_store: Any = None,
    require_durable_idempotency: bool = False,
    require_org_scope: bool = False,
) -> ExecutionRegistry:
    """Build fail-closed registry for live-safe business execution slice.

    Adapters registered: crm_internal, whatsapp_evolution, email_resend,
    calendar_calcom (primary), calendar_google (optional), fulfillment_service,
    billing_stripe (sandbox stub), accounting_erp (sandbox stub),
    fiscal_provider (sandbox stub).

    Approval is explicit: only adapters named in approved_adapters/config flags
    are marked approved. Missing config keeps adapters unapproved/fail-closed.
    sandbox_senders injects test/sandbox senders/clients/handlers by adapter name.
    """
    senders = dict(sandbox_senders or {})
    approved = _approved_set(approved_adapters, settings)
    registry = ExecutionRegistry(
        audit_callback=audit_callback,
        idempotency_store=idempotency_store,
        require_durable_idempotency=require_durable_idempotency,
        require_org_scope=require_org_scope,
    )

    def _mark_missing(name: str, *fields: str) -> None:
        registry.missing_config[name] = [f for f in fields if f]

    # CRM internal - uses internal DB, no external creds; config = db present.
    crm_name = "crm_internal"
    crm_requested = _is_approved(crm_name, approved=approved, settings=settings)
    crm_configured = db is not None
    if crm_requested and not crm_configured:
        _mark_missing(crm_name, "db")
    crm_approved = crm_requested and crm_configured
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
    if wa_requested and not wa_configured:
        missing = []
        if not str(wa_url or "").strip():
            missing.append("AIOS_EVOLUTION_SERVER_URL")
        if not str(wa_key or "").strip():
            missing.append("AIOS_EVOLUTION_API_KEY")
        _mark_missing(wa_name, *missing)
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
    if email_requested and not email_configured:
        missing = []
        if not str(email_cfg.get("RESEND_API_KEY") or "").strip():
            missing.append("AIOS_RESEND_API_KEY")
        if not str(email_cfg.get("from") or "").strip():
            missing.append("AIOS_RESEND_FROM_EMAIL")
        _mark_missing(email_name, *missing)
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
    if cal_event_type in (None, "", 0, "0"):
        event_type_id = _cfg(settings, "calcom_event_type_id", "CALCOM_EVENT_TYPE_ID")
        if event_type_id not in (None, "", 0, "0"):
            cal_event_type = str(event_type_id)
    cal_webhook = _cfg(settings, "calcom_webhook_secret", "CALCOM_WEBHOOK_SECRET")
    cal_cfg = dict(senders.get(f"{cal_name}_config") or {})
    cal_requested = _is_approved(cal_name, approved=approved, settings=settings)
    if cal_sender is not None and cal_requested:
        cal_api_key = cal_api_key or cal_cfg.get("api_key") or "sandbox-cal-key"
        cal_event_type = cal_event_type or cal_cfg.get("event_type") or "sandbox-event"
        cal_webhook = cal_webhook or cal_cfg.get("webhook_secret") or "sandbox-webhook"
    cal_configured = bool(cal_api_key and cal_event_type and cal_webhook)
    if cal_requested and not cal_configured:
        missing = []
        if not cal_api_key:
            missing.append("AIOS_CALCOM_API_KEY")
        if not cal_event_type:
            missing.append("AIOS_CALCOM_EVENT_TYPE/AIOS_CALCOM_EVENT_TYPE_ID")
        if not cal_webhook:
            missing.append("AIOS_CALCOM_WEBHOOK_SECRET")
        _mark_missing(cal_name, *missing)
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
    if gcal_requested and not gcal_configured:
        missing = []
        if not gcal_creds:
            missing.append("AIOS_GOOGLE_CALENDAR_CREDENTIALS")
        if not str(gcal_calendar_id or "").strip():
            missing.append("AIOS_GOOGLE_CALENDAR_ID")
        _mark_missing(gcal_name, *missing)
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
    if ff_requested and not ff_configured:
        missing = []
        if ff_handler is None:
            missing.append("sandbox_handler/fulfillment_handler")
        if not ff_steps:
            missing.append("AIOS_FULFILLMENT_STEPS")
        _mark_missing(ff_name, *missing)
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

    # Stripe billing/payments - sandbox sender injectable; no real HTTP/SDK calls.
    stripe_name = "billing_stripe"
    stripe_sender = senders.get(stripe_name) or senders.get("stripe")
    stripe_cfg = dict(senders.get(f"{stripe_name}_config") or {})
    stripe_secret = _cfg(settings, "stripe_secret_key", "STRIPE_SECRET_KEY")
    stripe_webhook = _cfg(settings, "stripe_webhook_secret", "STRIPE_WEBHOOK_SECRET")
    stripe_requested = _is_approved(stripe_name, approved=approved, settings=settings)
    stripe_sandbox_mode = bool(
        stripe_cfg.get("sandbox_mode")
        or stripe_cfg.get("sandbox")
        or _cfg(settings, "stripe_sandbox_mode", "STRIPE_SANDBOX_MODE", default=False)
    )
    if stripe_sender is not None and stripe_requested:
        stripe_secret = stripe_secret or stripe_cfg.get("secret_key") or "sk_test_sandbox_stub"
        stripe_webhook = stripe_webhook or stripe_cfg.get("webhook_secret") or "whsec_sandbox_stub"
        stripe_sandbox_mode = True
    stripe_configured = bool(str(stripe_secret or "").strip())
    if stripe_requested and not stripe_configured:
        _mark_missing(stripe_name, "AIOS_STRIPE_SECRET_KEY")
    # Fail closed unless explicitly approved, configured, and sandbox/test mode.
    stripe_approved = bool(stripe_requested and stripe_configured and stripe_sandbox_mode)
    if stripe_requested and stripe_configured and not stripe_sandbox_mode:
        # Explicit config present but sandbox not enabled - keep unapproved/fail-closed.
        _mark_missing(stripe_name, "AIOS_STRIPE_SANDBOX_MODE/sandbox sender")
    registry.register(
        StripeBillingAdapter(
            approved=stripe_approved,
            sandbox_mode=stripe_sandbox_mode,
            config={
                "STRIPE_SECRET_KEY": stripe_secret,
                "STRIPE_WEBHOOK_SECRET": stripe_webhook,
                **{k: v for k, v in stripe_cfg.items() if v is not None},
            },
            sender=stripe_sender,
            audit_callback=audit_callback,
        )
    )

    # Accounting/ERP - sandbox stub only; no real sync, no money movement.
    erp_name = "accounting_erp"
    erp_sender = senders.get(erp_name) or senders.get("erp")
    erp_cfg = dict(senders.get(f"{erp_name}_config") or {})
    erp_api_key = _cfg(settings, "accounting_erp_api_key", "ACCOUNTING_ERP_API_KEY")
    erp_base_url = _cfg(settings, "accounting_erp_base_url", "ACCOUNTING_ERP_BASE_URL")
    erp_requested = _is_approved(erp_name, approved=approved, settings=settings)
    erp_sandbox_mode = bool(
        erp_cfg.get("sandbox_mode")
        or erp_cfg.get("sandbox")
        or _cfg(settings, "accounting_erp_sandbox_mode", "ACCOUNTING_ERP_SANDBOX_MODE", default=False)
    )
    if erp_sender is not None and erp_requested:
        erp_api_key = erp_api_key or erp_cfg.get("api_key") or "sandbox-erp-key"
        erp_base_url = erp_base_url or erp_cfg.get("base_url") or "https://sandbox.erp.local"
        erp_sandbox_mode = True
    erp_configured = bool(str(erp_api_key or "").strip() and str(erp_base_url or "").strip())
    if erp_requested and not erp_configured:
        missing = []
        if not str(erp_api_key or "").strip():
            missing.append("AIOS_ACCOUNTING_ERP_API_KEY")
        if not str(erp_base_url or "").strip():
            missing.append("AIOS_ACCOUNTING_ERP_BASE_URL")
        _mark_missing(erp_name, *missing)
    erp_approved = bool(erp_requested and erp_configured and erp_sandbox_mode)
    if erp_requested and erp_configured and not erp_sandbox_mode:
        _mark_missing(erp_name, "AIOS_ACCOUNTING_ERP_SANDBOX_MODE/sandbox sender")
    registry.register(
        AccountingErpAdapter(
            approved=erp_approved,
            sandbox_mode=erp_sandbox_mode,
            config={
                "ACCOUNTING_ERP_API_KEY": erp_api_key,
                "ACCOUNTING_ERP_BASE_URL": erp_base_url,
                **{k: v for k, v in erp_cfg.items() if v is not None},
            },
            sender=erp_sender,
            audit_callback=audit_callback,
        )
    )

    # Fiscal/NF-e/tax provider - sandbox stub only; no real emission/tax calc.
    fiscal_name = "fiscal_provider"
    fiscal_sender = senders.get(fiscal_name) or senders.get("fiscal")
    fiscal_cfg = dict(senders.get(f"{fiscal_name}_config") or {})
    fiscal_api_key = _cfg(settings, "fiscal_provider_api_key", "FISCAL_PROVIDER_API_KEY")
    fiscal_base_url = _cfg(settings, "fiscal_provider_base_url", "FISCAL_PROVIDER_BASE_URL")
    fiscal_requested = _is_approved(fiscal_name, approved=approved, settings=settings)
    fiscal_sandbox_mode = bool(
        fiscal_cfg.get("sandbox_mode")
        or fiscal_cfg.get("sandbox")
        or _cfg(settings, "fiscal_provider_sandbox_mode", "FISCAL_PROVIDER_SANDBOX_MODE", default=False)
    )
    if fiscal_sender is not None and fiscal_requested:
        fiscal_api_key = fiscal_api_key or fiscal_cfg.get("api_key") or "sandbox-fiscal-key"
        fiscal_base_url = fiscal_base_url or fiscal_cfg.get("base_url") or "https://sandbox.fiscal.local"
        fiscal_sandbox_mode = True
    fiscal_configured = bool(str(fiscal_api_key or "").strip() and str(fiscal_base_url or "").strip())
    if fiscal_requested and not fiscal_configured:
        missing = []
        if not str(fiscal_api_key or "").strip():
            missing.append("AIOS_FISCAL_PROVIDER_API_KEY")
        if not str(fiscal_base_url or "").strip():
            missing.append("AIOS_FISCAL_PROVIDER_BASE_URL")
        _mark_missing(fiscal_name, *missing)
    fiscal_approved = bool(fiscal_requested and fiscal_configured and fiscal_sandbox_mode)
    if fiscal_requested and fiscal_configured and not fiscal_sandbox_mode:
        _mark_missing(fiscal_name, "AIOS_FISCAL_PROVIDER_SANDBOX_MODE/sandbox sender")
    registry.register(
        FiscalProviderAdapter(
            approved=fiscal_approved,
            sandbox_mode=fiscal_sandbox_mode,
            config={
                "FISCAL_PROVIDER_API_KEY": fiscal_api_key,
                "FISCAL_PROVIDER_BASE_URL": fiscal_base_url,
                **{k: v for k, v in fiscal_cfg.items() if v is not None},
            },
            sender=fiscal_sender,
            audit_callback=audit_callback,
        )
    )

    # Contract/e-sign - sandbox stub only; no real provider calls, no legal logic.
    esign_name = "contract_esign"
    esign_sender = senders.get(esign_name) or senders.get("esign")
    esign_cfg = dict(senders.get(f"{esign_name}_config") or {})
    esign_api_key = _cfg(settings, "contract_esign_api_key", "CONTRACT_ESIGN_API_KEY")
    esign_requested = _is_approved(esign_name, approved=approved, settings=settings)
    esign_sandbox_mode = bool(
        esign_cfg.get("sandbox_mode")
        or esign_cfg.get("sandbox")
        or _cfg(settings, "contract_esign_sandbox_mode", "CONTRACT_ESIGN_SANDBOX_MODE", default=False)
    )
    if esign_sender is not None and esign_requested:
        esign_api_key = esign_api_key or esign_cfg.get("api_key") or "sandbox-esign-key"
        esign_sandbox_mode = True
    esign_configured = bool(str(esign_api_key or "").strip())
    if esign_requested and not esign_configured:
        _mark_missing(esign_name, "AIOS_CONTRACT_ESIGN_API_KEY")
    esign_approved = bool(esign_requested and esign_configured and esign_sandbox_mode)
    if esign_requested and esign_configured and not esign_sandbox_mode:
        _mark_missing(esign_name, "AIOS_CONTRACT_ESIGN_SANDBOX_MODE/sandbox sender")
    registry.register(
        ContractEsignAdapter(
            approved=esign_approved,
            sandbox_mode=esign_sandbox_mode,
            config={
                "CONTRACT_ESIGN_API_KEY": esign_api_key,
                **{k: v for k, v in esign_cfg.items() if v is not None},
            },
            sender=esign_sender,
            audit_callback=audit_callback,
        )
    )

    # Payroll provider - sandbox stub only; no real provider calls, no payroll calculations.
    payroll_name = "payroll_provider"
    payroll_sender = senders.get(payroll_name) or senders.get("payroll")
    payroll_cfg = dict(senders.get(f"{payroll_name}_config") or {})
    payroll_api_key = _cfg(settings, "payroll_provider_api_key", "PAYROLL_PROVIDER_API_KEY")
    payroll_requested = _is_approved(payroll_name, approved=approved, settings=settings)
    payroll_sandbox_mode = bool(
        payroll_cfg.get("sandbox_mode")
        or payroll_cfg.get("sandbox")
        or _cfg(settings, "payroll_provider_sandbox_mode", "PAYROLL_PROVIDER_SANDBOX_MODE", default=False)
    )
    if payroll_sender is not None and payroll_requested:
        payroll_api_key = payroll_api_key or payroll_cfg.get("api_key") or "sandbox-payroll-key"
        payroll_sandbox_mode = True
    payroll_configured = bool(str(payroll_api_key or "").strip())
    if payroll_requested and not payroll_configured:
        _mark_missing(payroll_name, "AIOS_PAYROLL_PROVIDER_API_KEY")
    payroll_approved = bool(payroll_requested and payroll_configured and payroll_sandbox_mode)
    if payroll_requested and payroll_configured and not payroll_sandbox_mode:
        _mark_missing(payroll_name, "AIOS_PAYROLL_PROVIDER_SANDBOX_MODE/sandbox sender")
    registry.register(
        PayrollProviderAdapter(
            approved=payroll_approved,
            sandbox_mode=payroll_sandbox_mode,
            config={
                "PAYROLL_PROVIDER_API_KEY": payroll_api_key,
                **{k: v for k, v in payroll_cfg.items() if v is not None},
            },
            sender=payroll_sender,
            audit_callback=audit_callback,
        )
    )

    # Tax/fiscal rail - sandbox stub only; no real provider calls, no tax calculations.
    tax_name = "tax_fiscal"
    tax_sender = senders.get(tax_name) or senders.get("tax")
    tax_cfg = dict(senders.get(f"{tax_name}_config") or {})
    tax_api_key = _cfg(settings, "tax_fiscal_api_key", "TAX_FISCAL_API_KEY")
    tax_requested = _is_approved(tax_name, approved=approved, settings=settings)
    tax_sandbox_mode = bool(
        tax_cfg.get("sandbox_mode")
        or tax_cfg.get("sandbox")
        or _cfg(settings, "tax_fiscal_sandbox_mode", "TAX_FISCAL_SANDBOX_MODE", default=False)
    )
    if tax_sender is not None and tax_requested:
        tax_api_key = tax_api_key or tax_cfg.get("api_key") or "sandbox-tax-key"
        tax_sandbox_mode = True
    tax_configured = bool(str(tax_api_key or "").strip())
    if tax_requested and not tax_configured:
        _mark_missing(tax_name, "AIOS_TAX_FISCAL_API_KEY")
    tax_approved = bool(tax_requested and tax_configured and tax_sandbox_mode)
    if tax_requested and tax_configured and not tax_sandbox_mode:
        _mark_missing(tax_name, "AIOS_TAX_FISCAL_SANDBOX_MODE/sandbox sender")
    registry.register(
        TaxFiscalAdapter(
            approved=tax_approved,
            sandbox_mode=tax_sandbox_mode,
            config={
                "TAX_FISCAL_API_KEY": tax_api_key,
                **{k: v for k, v in tax_cfg.items() if v is not None},
            },
            sender=tax_sender,
            audit_callback=audit_callback,
        )
    )

    return registry
