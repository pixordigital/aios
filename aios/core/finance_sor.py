"""Minimal internal finance/legal SOR service.

Fail-closed org scoping. No external provider integration, no money movement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from aios.db.models import (
    FinanceContract,
    FinanceContractVersion,
    FinanceInvoice,
    FinanceInvoiceLine,
    FinanceLedgerEntry,
    FinancePayment,
    FinanceRefund,
)

FINANCE_ENTITIES: dict[str, dict[str, Any]] = {
    "contract": {
        "model": FinanceContract,
        "statuses": {"draft", "active", "suspended", "terminated", "cancelled"},
    },
    "contract_version": {
        "model": FinanceContractVersion,
        "statuses": {"draft", "pending_approval", "approved", "effective", "superseded", "void"},
    },
    "invoice": {
        "model": FinanceInvoice,
        "statuses": {"draft", "issued", "partially_paid", "paid", "void", "overdue"},
    },
    "invoice_line": {
        "model": FinanceInvoiceLine,
        "statuses": set(),
    },
    "payment": {
        "model": FinancePayment,
        "statuses": {"pending", "succeeded", "failed", "cancelled", "refunded"},
    },
    "refund": {
        "model": FinanceRefund,
        "statuses": {"pending", "succeeded", "failed", "cancelled"},
    },
    "ledger_entry": {
        "model": FinanceLedgerEntry,
        "statuses": set(),
    },
}

_MONEY_MOVEMENT_FIELDS = {
    "provider_charge_id",
    "capture",
    "settle",
    "payout",
    "transfer",
}

_POSTABLE_SOURCE_ENTITIES = {"invoice", "payment", "refund"}
_RECONCILIATION_STATES = {"pending", "reconciled", "mismatch"}

_LEDGER_ACCOUNT_CODES = {
    "invoice": ("accounts_receivable", "revenue"),
    "payment": ("cash", "accounts_receivable"),
    "refund": ("refunds_payable", "cash"),
}


class FinanceSORValidationError(ValueError):
    pass


class FinanceSORAccessError(PermissionError):
    pass


class FinanceSORConflictError(RuntimeError):
    pass


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_org_id(org_id: str | None) -> str:
    oid = str(org_id or "").strip()
    if not oid:
        raise FinanceSORAccessError("org_id required")
    return oid


def _entity_cfg(entity: str) -> dict[str, Any]:
    cfg = FINANCE_ENTITIES.get(str(entity or "").strip().lower())
    if not cfg:
        raise FinanceSORValidationError(f"unknown finance entity: {entity}")
    return cfg


def _model_columns(model: type) -> set[str]:
    return {c.name for c in model.__table__.columns}


def _validate_status(cfg: dict[str, Any], data: dict[str, Any]) -> None:
    allowed = cfg.get("statuses") or set()
    if not allowed or "status" not in data:
        return
    status = str(data.get("status") or "").strip()
    if status not in allowed:
        raise FinanceSORValidationError(f"invalid status: {status}")


def _sanitize_data(model: type, data: dict[str, Any]) -> dict[str, Any]:
    cols = _model_columns(model)
    clean: dict[str, Any] = {}
    for k, v in (data or {}).items():
        key = str(k)
        if key == "org_id":
            continue
        if key in _MONEY_MOVEMENT_FIELDS:
            raise FinanceSORValidationError(f"field not allowed: {key}")
        if key in cols:
            clean[key] = v
    return clean


async def _find_by_idempotency(db: Any, model: type, org_id: str, idempotency_key: str):
    key = str(idempotency_key or "").strip()
    if not key or "idempotency_key" not in _model_columns(model):
        return None
    stmt = select(model).where(model.org_id == org_id, model.idempotency_key == key)
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_finance_record(
    db: Any,
    *,
    org_id: str,
    entity: str,
    data: dict[str, Any] | None = None,
) -> Any:
    oid = _require_org_id(org_id)
    cfg = _entity_cfg(entity)
    model = cfg["model"]
    payload = _sanitize_data(model, data or {})
    payload["org_id"] = oid
    _validate_status(cfg, payload)

    idem = payload.get("idempotency_key")
    if idem:
        existing = await _find_by_idempotency(db, model, oid, str(idem))
        if existing is not None:
            return existing

    obj = model(**payload)
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        idem = payload.get("idempotency_key")
        if idem:
            existing = await _find_by_idempotency(db, model, oid, str(idem))
            if existing is not None:
                return existing
        raise
    try:
        await db.refresh(obj)
    except Exception:
        pass
    return obj


async def get_finance_record(
    db: Any,
    *,
    org_id: str,
    entity: str,
    record_id: str,
) -> Any | None:
    oid = _require_org_id(org_id)
    cfg = _entity_cfg(entity)
    model = cfg["model"]
    rid = str(record_id or "").strip()
    if not rid:
        return None
    stmt = select(model).where(model.id == rid, model.org_id == oid)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_finance_records(
    db: Any,
    *,
    org_id: str,
    entity: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Any]:
    oid = _require_org_id(org_id)
    cfg = _entity_cfg(entity)
    model = cfg["model"]
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    stmt = select(model).where(model.org_id == oid)
    if status is not None:
        st = str(status).strip()
        if "status" in _model_columns(model):
            if cfg["statuses"] and st not in cfg["statuses"]:
                raise FinanceSORValidationError(f"invalid status: {st}")
            stmt = stmt.where(model.status == st)
    if hasattr(model, "created_at"):
        stmt = stmt.order_by(model.created_at.desc())
    stmt = stmt.offset(off).limit(lim)
    return list((await db.execute(stmt)).scalars().all())


def _normalize_currency(value: Any, *, field: str = "currency") -> str:
    cur = str(value or "").strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        raise FinanceSORValidationError(f"invalid {field}: {value!r}")
    return cur


def _normalize_amount_minor(value: Any, *, field: str = "amount_minor") -> int:
    if isinstance(value, bool) or value is None:
        raise FinanceSORValidationError(f"invalid {field}: {value!r}")
    try:
        amt = int(value)
    except Exception as exc:
        raise FinanceSORValidationError(f"invalid {field}: {value!r}") from exc
    if amt <= 0:
        raise FinanceSORValidationError(f"{field} must be positive")
    return amt


def _require_idempotency_key(value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        raise FinanceSORValidationError("idempotency_key required")
    return key


async def _get_posting_source(db: Any, *, org_id: str, entity: str, record_id: str):
    ent = str(entity or "").strip().lower()
    if ent not in _POSTABLE_SOURCE_ENTITIES:
        raise FinanceSORValidationError(f"unsupported posting source entity: {entity}")
    rid = str(record_id or "").strip()
    if not rid:
        raise FinanceSORValidationError("record_id required")
    row = await get_finance_record(db, org_id=org_id, entity=ent, record_id=rid)
    if row is None:
        # fail closed: missing or cross-org indistinguishable
        raise FinanceSORAccessError(f"{ent} not found for org")
    return ent, row


def _posting_source_amount(ent: str, row: Any) -> int:
    if ent == "invoice":
        return _normalize_amount_minor(getattr(row, "total_minor", None), field="total_minor")
    return _normalize_amount_minor(getattr(row, "amount_minor", None), field="amount_minor")


def _posting_source_currency(ent: str, row: Any) -> str:
    return _normalize_currency(getattr(row, "currency", None))


def _posting_source_status(ent: str, row: Any) -> str:
    return str(getattr(row, "status", "") or "").strip()


def _validate_posting_source(ent: str, row: Any) -> None:
    status = _posting_source_status(ent, row)
    if ent == "invoice":
        if status not in {"issued", "partially_paid", "paid", "overdue"}:
            raise FinanceSORValidationError(f"invoice status not postable: {status}")
    elif ent == "payment":
        if status != "succeeded":
            raise FinanceSORValidationError(f"payment status not postable: {status}")
    elif ent == "refund":
        if status != "succeeded":
            raise FinanceSORValidationError(f"refund status not postable: {status}")


def _entry_refs_for_source(ent: str, row: Any) -> dict[str, str | None]:
    refs = {
        "contract_id": getattr(row, "contract_id", None),
        "invoice_id": getattr(row, "invoice_id", None),
        "payment_id": getattr(row, "payment_id", None),
        "refund_id": getattr(row, "refund_id", None),
    }
    if ent == "invoice":
        refs["invoice_id"] = row.id
    elif ent == "payment":
        refs["payment_id"] = row.id
    elif ent == "refund":
        refs["refund_id"] = row.id
    return refs


def _ledger_specs(ent: str, *, amount_minor: int, currency: str, occurred_at: datetime) -> list[dict[str, Any]]:
    debit_acct, credit_acct = _LEDGER_ACCOUNT_CODES[ent]
    base = {
        "entry_type": ent,
        "currency": currency,
        "amount_minor": amount_minor,
        "occurred_at": occurred_at,
    }
    return [
        {**base, "direction": "debit", "account_code": debit_acct},
        {**base, "direction": "credit", "account_code": credit_acct},
    ]


def _validate_balanced_entries(entries: list[dict[str, Any]]) -> None:
    if len(entries) < 2:
        raise FinanceSORValidationError("ledger posting must have at least 2 entries")
    debit = 0
    credit = 0
    currencies = set()
    for e in entries:
        direction = str(e.get("direction") or "").strip().lower()
        amt = _normalize_amount_minor(e.get("amount_minor"), field="amount_minor")
        cur = _normalize_currency(e.get("currency"))
        currencies.add(cur)
        if direction == "debit":
            debit += amt
        elif direction == "credit":
            credit += amt
        else:
            raise FinanceSORValidationError(f"invalid ledger direction: {direction}")
    if len(currencies) != 1:
        raise FinanceSORValidationError("ledger entries currency mismatch")
    if debit != credit:
        raise FinanceSORValidationError(f"ledger imbalance: debit={debit} credit={credit}")


async def _find_posting_entries(db: Any, *, org_id: str, posting_key: str) -> list[FinanceLedgerEntry]:
    stmt = (
        select(FinanceLedgerEntry)
        .where(FinanceLedgerEntry.org_id == org_id)
        .where(FinanceLedgerEntry.extra_data["posting_key"].as_string() == posting_key)
        .order_by(FinanceLedgerEntry.created_at.asc(), FinanceLedgerEntry.id.asc())
    )
    try:
        rows = list((await db.execute(stmt)).scalars().all())
    except Exception:
        # SQLite JSON path support varies; fallback to scan small candidate set by source_ref/idempotency prefix.
        stmt2 = select(FinanceLedgerEntry).where(FinanceLedgerEntry.org_id == org_id)
        rows = []
        for r in (await db.execute(stmt2)).scalars().all():
            ed = r.extra_data if isinstance(getattr(r, "extra_data", None), dict) else {}
            if str(ed.get("posting_key") or "") == posting_key:
                rows.append(r)
        rows.sort(key=lambda r: (getattr(r, "created_at", None) or _utcnow_naive(), str(getattr(r, "id", ""))))
    return rows


def _posting_result(entries: list[FinanceLedgerEntry], *, deduped: bool) -> dict[str, Any]:
    debit = sum(int(getattr(e, "amount_minor", 0) or 0) for e in entries if e.direction == "debit")
    credit = sum(int(getattr(e, "amount_minor", 0) or 0) for e in entries if e.direction == "credit")
    first = entries[0] if entries else None
    ed = first.extra_data if first and isinstance(first.extra_data, dict) else {}
    return {
        "ok": True,
        "deduped": deduped,
        "posting_key": ed.get("posting_key"),
        "source_entity": ed.get("source_entity"),
        "source_id": ed.get("source_id"),
        "entry_ids": [e.id for e in entries],
        "debit_minor": debit,
        "credit_minor": credit,
        "balanced": debit == credit,
    }


async def post_balanced_ledger_entries(
    db: Any,
    *,
    org_id: str,
    source_entity: str,
    source_id: str,
    idempotency_key: str,
    entry_type: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Create balanced internal ledger entries for an existing finance record.

    Fail-closed: org scope, source existence, status, amount/currency, balance,
    duplicate idempotency key conflicts. No provider calls, no money movement.
    """
    oid = _require_org_id(org_id)
    key = _require_idempotency_key(idempotency_key)
    ent, row = await _get_posting_source(db, org_id=oid, entity=source_entity, record_id=source_id)
    if str(getattr(row, "org_id", "")) != oid:
        raise FinanceSORAccessError("cross-org source access denied")
    _validate_posting_source(ent, row)
    amount = _posting_source_amount(ent, row)
    currency = _posting_source_currency(ent, row)
    when = occurred_at or getattr(row, "paid_at", None) or getattr(row, "refunded_at", None) or getattr(row, "issued_at", None) or _utcnow_naive()
    etype = str(entry_type or ent).strip().lower() or ent
    if etype != ent:
        raise FinanceSORValidationError(f"entry_type must match source entity: {ent}")

    existing = await _find_posting_entries(db, org_id=oid, posting_key=key)
    if existing:
        e0 = existing[0]
        ed = e0.extra_data if isinstance(e0.extra_data, dict) else {}
        if str(ed.get("source_entity") or "") != ent or str(ed.get("source_id") or "") != str(row.id):
            raise FinanceSORConflictError("idempotency key already used for different posting")
        _validate_balanced_entries([
            {"direction": e.direction, "amount_minor": e.amount_minor, "currency": e.currency} for e in existing
        ])
        return _posting_result(existing, deduped=True)

    specs = _ledger_specs(ent, amount_minor=amount, currency=currency, occurred_at=when)
    _validate_balanced_entries(specs)
    refs = _entry_refs_for_source(ent, row)

    created: list[FinanceLedgerEntry] = []
    for idx, spec in enumerate(specs):
        entry = FinanceLedgerEntry(
            org_id=oid,
            entry_type=etype,
            direction=spec["direction"],
            account_code=spec["account_code"],
            amount_minor=spec["amount_minor"],
            currency=spec["currency"],
            occurred_at=spec["occurred_at"],
            contract_id=refs.get("contract_id"),
            invoice_id=refs.get("invoice_id"),
            payment_id=refs.get("payment_id"),
            refund_id=refs.get("refund_id"),
            source_system="aios_finance_sor",
            source_ref=f"{ent}:{row.id}",
            idempotency_key=f"{key}:{idx}",
            posted_at=_utcnow_naive(),
            extra_data={
                "posting_key": key,
                "source_entity": ent,
                "source_id": str(row.id),
                "source_status": _posting_source_status(ent, row),
                "balanced": True,
            },
        )
        db.add(entry)
        created.append(entry)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        existing = await _find_posting_entries(db, org_id=oid, posting_key=key)
        if existing:
            e0 = existing[0]
            ed = e0.extra_data if isinstance(e0.extra_data, dict) else {}
            if str(ed.get("source_entity") or "") != ent or str(ed.get("source_id") or "") != str(row.id):
                raise FinanceSORConflictError("idempotency key already used for different posting") from exc
            return _posting_result(existing, deduped=True)
        raise

    for e in created:
        try:
            await db.refresh(e)
        except Exception:
            pass
    return _posting_result(created, deduped=False)


def _reconciliation_payload(
    *,
    state: str,
    reason: str,
    source_entity: str,
    source_id: str,
    linked_entity: str | None = None,
    linked_id: str | None = None,
) -> dict[str, Any]:
    st = str(state or "").strip().lower()
    if st not in _RECONCILIATION_STATES:
        raise FinanceSORValidationError(f"invalid reconciliation state: {state}")
    rsn = str(reason or "").strip()
    if not rsn:
        raise FinanceSORValidationError("reconciliation reason required")
    return {
        "state": st,
        "reason": rsn,
        "source_entity": source_entity,
        "source_id": source_id,
        "linked_entity": str(linked_entity).strip().lower() if linked_entity else None,
        "linked_id": str(linked_id).strip() if linked_id else None,
        "updated_at": _utcnow_naive().isoformat(),
    }


async def mark_finance_reconciliation(
    db: Any,
    *,
    org_id: str,
    entity: str,
    record_id: str,
    state: str,
    reason: str,
    linked_entity: str | None = None,
    linked_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Mark/link a finance SOR record reconciliation state in extra_data.

    No external provider. Fail-closed on missing/cross-org refs and bad state.
    """
    oid = _require_org_id(org_id)
    ent = str(entity or "").strip().lower()
    _entity_cfg(ent)
    row = await get_finance_record(db, org_id=oid, entity=ent, record_id=record_id)
    if row is None:
        raise FinanceSORAccessError(f"{ent} not found for org")
    if str(getattr(row, "org_id", "")) != oid:
        raise FinanceSORAccessError("cross-org access denied")

    if linked_entity or linked_id:
        if not linked_entity or not linked_id:
            raise FinanceSORValidationError("linked_entity and linked_id required together")
        l_ent = str(linked_entity).strip().lower()
        _entity_cfg(l_ent)
        linked = await get_finance_record(db, org_id=oid, entity=l_ent, record_id=str(linked_id))
        if linked is None:
            raise FinanceSORAccessError(f"linked {l_ent} not found for org")
        if str(getattr(linked, "org_id", "")) != oid:
            raise FinanceSORAccessError("cross-org linked access denied")

    payload = _reconciliation_payload(
        state=state,
        reason=reason,
        source_entity=ent,
        source_id=str(row.id),
        linked_entity=linked_entity,
        linked_id=linked_id,
    )
    idem = str(idempotency_key or "").strip() or None
    if idem:
        payload["idempotency_key"] = idem

    extra = dict(getattr(row, "extra_data", None) or {})
    prev = extra.get("reconciliation")
    if idem and isinstance(prev, dict) and str(prev.get("idempotency_key") or "") == idem:
        prev_cmp = {k: prev.get(k) for k in ("state", "reason", "source_entity", "source_id", "linked_entity", "linked_id")}
        new_cmp = {k: payload.get(k) for k in prev_cmp}
        if prev_cmp == new_cmp:
            return {"ok": True, "deduped": True, "entity": ent, "record_id": str(row.id), "reconciliation": prev}
        raise FinanceSORConflictError("idempotency key already used for different reconciliation")

    extra["reconciliation"] = payload
    row.extra_data = extra
    await db.flush()
    try:
        await db.refresh(row)
    except Exception:
        pass
    return {
        "ok": True,
        "deduped": False,
        "entity": ent,
        "record_id": str(row.id),
        "reconciliation": payload,
    }


def _normalize_reconciliation_state(value: Any) -> str | None:
    if value is None:
        return None
    st = str(value).strip().lower()
    if not st:
        return None
    if st not in _RECONCILIATION_STATES:
        raise FinanceSORValidationError(f"invalid reconciliation state: {value}")
    return st


async def get_finance_reconciliation(
    db: Any,
    *,
    org_id: str,
    entity: str,
    record_id: str,
) -> dict[str, Any]:
    oid = _require_org_id(org_id)
    ent = str(entity or "").strip().lower()
    _entity_cfg(ent)
    row = await get_finance_record(db, org_id=oid, entity=ent, record_id=record_id)
    if row is None:
        raise FinanceSORAccessError(f"{ent} not found for org")
    extra = getattr(row, "extra_data", None) or {}
    rec = extra.get("reconciliation") if isinstance(extra, dict) else None
    if not isinstance(rec, dict):
        rec = {"state": "pending", "reason": "not_reconciled", "source_entity": ent, "source_id": str(row.id)}
    return {"entity": ent, "record_id": str(row.id), "reconciliation": rec}


async def list_finance_reconciliations(
    db: Any,
    *,
    org_id: str,
    entity: str | None = None,
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List reconciliation status for finance records. Read-only, org-scoped."""
    oid = _require_org_id(org_id)
    wanted_state = _normalize_reconciliation_state(state)
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))

    entities: list[str]
    if entity is None or not str(entity).strip():
        entities = [e for e in FINANCE_ENTITIES.keys() if e != "ledger_entry"]
    else:
        ent = str(entity).strip().lower()
        _entity_cfg(ent)
        entities = [ent]

    items: list[dict[str, Any]] = []
    # Deterministic scan: entity name then created_at desc when available.
    for ent in entities:
        model = FINANCE_ENTITIES[ent]["model"]
        stmt = select(model).where(model.org_id == oid)
        if hasattr(model, "created_at"):
            stmt = stmt.order_by(model.created_at.desc())
        rows = list((await db.execute(stmt)).scalars().all())
        for row in rows:
            rec = await get_finance_reconciliation(db, org_id=oid, entity=ent, record_id=str(row.id))
            rec_state = str((rec.get("reconciliation") or {}).get("state") or "pending")
            if wanted_state and rec_state != wanted_state:
                continue
            items.append(rec)

    # Stable order across entities: entity, record_id
    items.sort(key=lambda r: (str(r.get("entity") or ""), str(r.get("record_id") or "")))
    return items[off : off + lim]


async def list_posted_ledger_entries(
    db: Any,
    *,
    org_id: str,
    source_entity: str | None = None,
    source_id: str | None = None,
    posting_key: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Any]:
    """List posted ledger entries by source/posting filters. Read-only, org-scoped."""
    oid = _require_org_id(org_id)
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))

    src_ent = str(source_entity or "").strip().lower() or None
    if src_ent is not None and src_ent not in _POSTABLE_SOURCE_ENTITIES:
        raise FinanceSORValidationError(f"unsupported posting source entity: {source_entity}")
    src_id = str(source_id or "").strip() or None
    pkey = str(posting_key or "").strip() or None
    if src_id and not src_ent:
        raise FinanceSORValidationError("source_entity required with source_id")

    stmt = select(FinanceLedgerEntry).where(FinanceLedgerEntry.org_id == oid)
    # Fast path on indexed columns when possible.
    if src_ent == "invoice" and src_id:
        stmt = stmt.where(FinanceLedgerEntry.invoice_id == src_id)
    elif src_ent == "payment" and src_id:
        stmt = stmt.where(FinanceLedgerEntry.payment_id == src_id)
    elif src_ent == "refund" and src_id:
        stmt = stmt.where(FinanceLedgerEntry.refund_id == src_id)
    if pkey:
        # posting idempotency stored as "<key>:<idx>"; prefix match keeps index use possible in some DBs.
        stmt = stmt.where(FinanceLedgerEntry.idempotency_key.like(f"{pkey}:%"))

    stmt = stmt.order_by(FinanceLedgerEntry.created_at.desc(), FinanceLedgerEntry.id.desc())
    rows = list((await db.execute(stmt)).scalars().all())

    out: list[FinanceLedgerEntry] = []
    for r in rows:
        ed = r.extra_data if isinstance(getattr(r, "extra_data", None), dict) else {}
        r_ent = str(ed.get("source_entity") or "").strip().lower() or None
        r_id = str(ed.get("source_id") or "").strip() or None
        r_pkey = str(ed.get("posting_key") or "").strip() or None
        if src_ent and r_ent != src_ent:
            continue
        if src_id and r_id != src_id:
            continue
        if pkey and r_pkey != pkey:
            continue
        # "posted ledger entries visibility" - only entries with posting metadata or posted_at.
        if not r_pkey and getattr(r, "posted_at", None) is None:
            continue
        out.append(r)

    return out[off : off + lim]


__all__ = [
    "FINANCE_ENTITIES",
    "FinanceSORAccessError",
    "FinanceSORConflictError",
    "FinanceSORValidationError",
    "create_finance_record",
    "get_finance_record",
    "get_finance_reconciliation",
    "list_finance_reconciliations",
    "list_finance_records",
    "list_posted_ledger_entries",
    "mark_finance_reconciliation",
    "post_balanced_ledger_entries",
]
