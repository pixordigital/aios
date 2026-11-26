"""Fail-closed internal CRM adapter scaffold.

No external creds. Side effects require idempotency_key + org_id + db/session.
Actions: upsert_contact, upsert_deal, add_activity. No delete/bulk.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aios.core.business_execution import ExecutionDenied, ExecutionResult

logger = logging.getLogger(__name__)

AuditCallback = Callable[[dict[str, Any]], None]

_ALLOWED_ACTIONS = {"upsert_contact", "upsert_deal", "add_activity"}
_DESTRUCTIVE_TOKENS = ("delete", "bulk", "drop", "truncate", "purge", "remove")


def _is_destructive(action: str) -> bool:
    a = (action or "").lower()
    return any(tok in a for tok in _DESTRUCTIVE_TOKENS)


class CrmInternalAdapter:
    name = "crm_internal"

    def __init__(
        self,
        *,
        db: Any = None,
        session: Any = None,
        approved: bool = False,
        audit_callback: AuditCallback | None = None,
    ) -> None:
        self._db = db if db is not None else session
        self.approved = bool(approved)
        self._audit_callback = audit_callback

    def _audit(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("adapter", self.name)
        logger.info("crm_internal.audit %s", payload)
        if self._audit_callback is not None:
            self._audit_callback(payload)

    def _deny(self, *, action: str, idempotency_key: str, reason: str) -> ExecutionDenied:
        self._audit(
            {
                "event": "crm_internal.denied",
                "action": action,
                "idempotency_key": idempotency_key,
                "ok": False,
                "reason": reason,
            }
        )
        return ExecutionDenied(reason)

    def execute(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ExecutionResult:
        action_name = str(action or "").strip()
        key = str(idempotency_key or "").strip()
        data = dict(payload or {})
        org_id = str(data.get("org_id") or "").strip()

        if self._db is None:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="db/session not provided (fail-closed)",
            )
        if not key:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="idempotency_key required",
            )
        if not org_id:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="org_id required",
            )
        if not action_name or action_name not in _ALLOWED_ACTIONS or _is_destructive(action_name):
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason=f"action not allowed: {action_name}",
            )

        self._audit(
            {
                "event": "crm_internal.start",
                "action": action_name,
                "idempotency_key": key,
                "org_id": org_id,
                "ok": None,
            }
        )

        try:
            if action_name == "upsert_contact":
                result = self._upsert_contact(data=data, idempotency_key=key)
            elif action_name == "upsert_deal":
                result = self._upsert_deal(data=data, idempotency_key=key)
            elif action_name == "add_activity":
                result = self._add_activity(data=data, idempotency_key=key)
            else:  # pragma: no cover - guarded above
                raise self._deny(
                    action=action_name,
                    idempotency_key=key,
                    reason=f"action not allowed: {action_name}",
                )
        except ExecutionDenied:
            raise
        except Exception as exc:
            self._audit(
                {
                    "event": "crm_internal.error",
                    "action": action_name,
                    "idempotency_key": key,
                    "org_id": org_id,
                    "ok": False,
                    "reason": str(exc),
                }
            )
            raise

        self._audit(
            {
                "event": "crm_internal.result",
                "action": action_name,
                "idempotency_key": key,
                "org_id": org_id,
                "ok": result.ok,
                "status": result.status,
            }
        )
        return result

    def _upsert_contact(self, *, data: dict[str, Any], idempotency_key: str) -> ExecutionResult:
        try:
            from aios.core.crm_intelligence import Contact
        except Exception as exc:
            raise self._deny(
                action="upsert_contact",
                idempotency_key=idempotency_key,
                reason=f"CrmContact model unavailable (TODO): {exc}",
            )

        org_id = str(data["org_id"])
        email = str(data.get("email") or data.get("lead_email") or "").strip()
        name = str(data.get("name") or data.get("lead_name") or "").strip()
        if not email and not name:
            raise self._deny(
                action="upsert_contact",
                idempotency_key=idempotency_key,
                reason="email or name required",
            )

        contact = self._find_existing(Contact, org_id=org_id, email=email)
        created = contact is None
        if created:
            contact = Contact(
                org_id=org_id,
                name=name or email,
                email=email,
                phone=str(data.get("phone") or ""),
                role=str(data.get("role") or ""),
                source=str(data.get("source") or "crm_internal_adapter"),
            )
            extra = dict(getattr(contact, "extra_data", {}) or {})
            extra["idempotency_key"] = idempotency_key
            contact.extra_data = extra
            self._db_add(contact)
        else:
            if name:
                contact.name = name
            if data.get("phone"):
                contact.phone = str(data["phone"])
            if data.get("role"):
                contact.role = str(data["role"])
            extra = dict(getattr(contact, "extra_data", {}) or {})
            extra.setdefault("idempotency_key", idempotency_key)
            contact.extra_data = extra

        self._db_flush()
        return ExecutionResult(
            ok=True,
            adapter=self.name,
            action="upsert_contact",
            idempotency_key=idempotency_key,
            status="created" if created else "updated",
            detail="contact upserted",
            data={
                "contact_id": getattr(contact, "id", None),
                "org_id": org_id,
                "email": email,
                "created": created,
            },
        )

    def _upsert_deal(self, *, data: dict[str, Any], idempotency_key: str) -> ExecutionResult:
        try:
            from aios.db.models import CrmDeal
        except Exception as exc:
            raise self._deny(
                action="upsert_deal",
                idempotency_key=idempotency_key,
                reason=f"CrmDeal model unavailable (TODO): {exc}",
            )

        org_id = str(data["org_id"])
        deal_id = str(data.get("deal_id") or "").strip() or None
        lead_email = str(data.get("lead_email") or data.get("email") or "").strip()
        lead_name = str(data.get("lead_name") or data.get("name") or "").strip()
        if not deal_id and not lead_email and not lead_name:
            raise self._deny(
                action="upsert_deal",
                idempotency_key=idempotency_key,
                reason="deal_id, lead_email, or lead_name required",
            )

        deal = None
        if deal_id is not None:
            getter = getattr(self._db, "get", None)
            if callable(getter):
                deal = getter(CrmDeal, deal_id)
        if deal is None and lead_email:
            deal = self._find_existing_deal(CrmDeal, org_id=org_id, lead_email=lead_email)

        created = deal is None
        if created:
            deal = CrmDeal(
                org_id=org_id,
                lead_name=lead_name or lead_email,
                lead_email=lead_email,
                lead_phone=str(data.get("lead_phone") or data.get("phone") or ""),
                stage=str(data.get("stage") or "prospection"),
                value=float(data.get("value") or 0),
                source=str(data.get("source") or "crm_internal_adapter"),
            )
            extra = dict(getattr(deal, "extra_data", {}) or {})
            extra["idempotency_key"] = idempotency_key
            deal.extra_data = extra
            self._db_add(deal)
        else:
            if lead_name:
                deal.lead_name = lead_name
            if lead_email:
                deal.lead_email = lead_email
            if "value" in data:
                deal.value = float(data.get("value") or 0)
            if data.get("stage"):
                deal.stage = str(data["stage"])
            extra = dict(getattr(deal, "extra_data", {}) or {})
            extra.setdefault("idempotency_key", idempotency_key)
            deal.extra_data = extra

        self._db_flush()
        return ExecutionResult(
            ok=True,
            adapter=self.name,
            action="upsert_deal",
            idempotency_key=idempotency_key,
            status="created" if created else "updated",
            detail="deal upserted",
            data={
                "deal_id": getattr(deal, "id", None),
                "org_id": org_id,
                "lead_email": lead_email,
                "created": created,
            },
        )

    def _add_activity(self, *, data: dict[str, Any], idempotency_key: str) -> ExecutionResult:
        try:
            from aios.core.crm_intelligence import InteractionEvent
        except Exception as exc:
            raise self._deny(
                action="add_activity",
                idempotency_key=idempotency_key,
                reason=f"CrmActivity model unavailable (TODO): {exc}",
            )

        org_id = str(data["org_id"])
        summary = str(data.get("summary") or data.get("notes") or "").strip()
        if not summary:
            raise self._deny(
                action="add_activity",
                idempotency_key=idempotency_key,
                reason="summary required",
            )

        activity = InteractionEvent(
            org_id=org_id,
            account_id=data.get("account_id"),
            contact_id=data.get("contact_id"),
            deal_id=data.get("deal_id"),
            channel=str(data.get("channel") or "internal"),
            direction=str(data.get("direction") or "outbound"),
            event_type=str(data.get("event_type") or "activity"),
            summary=summary,
            source=str(data.get("source") or "crm_internal_adapter"),
            provenance={
                "idempotency_key": idempotency_key,
                "adapter": self.name,
            },
        )
        self._db_add(activity)
        self._db_flush()
        return ExecutionResult(
            ok=True,
            adapter=self.name,
            action="add_activity",
            idempotency_key=idempotency_key,
            status="created",
            detail="activity added",
            data={
                "activity_id": getattr(activity, "id", None),
                "org_id": org_id,
                "deal_id": data.get("deal_id"),
            },
        )

    def _db_add(self, obj: Any) -> None:
        add = getattr(self._db, "add", None)
        if callable(add):
            add(obj)

    def _db_flush(self) -> None:
        flush = getattr(self._db, "flush", None)
        if callable(flush):
            res = flush()
            # async sessions return coroutine; scaffold stays sync, but don't crash on mock
            if hasattr(res, "__await__"):
                close = getattr(res, "close", None)
                if callable(close):
                    close()

    def _find_existing(self, model: Any, *, org_id: str, email: str) -> Any | None:
        if not email:
            return None
        # Best-effort: support mock session with .query()/.execute() or simple attribute
        query = getattr(self._db, "query", None)
        if callable(query):
            try:
                q = query(model)
                filt = getattr(q, "filter_by", None)
                if callable(filt):
                    q = filt(org_id=org_id, email=email)
                first = getattr(q, "first", None)
                if callable(first):
                    return first()
            except Exception:
                return None
        return None

    def _find_existing_deal(self, model: Any, *, org_id: str, lead_email: str) -> Any | None:
        if not lead_email:
            return None
        query = getattr(self._db, "query", None)
        if callable(query):
            try:
                q = query(model)
                filt = getattr(q, "filter_by", None)
                if callable(filt):
                    q = filt(org_id=org_id, lead_email=lead_email)
                first = getattr(q, "first", None)
                if callable(first):
                    return first()
            except Exception:
                return None
        return None
