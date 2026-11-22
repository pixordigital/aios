"""Authoritative KPIs: deterministic Python/SQL calculations. LLMs interpret, never decide.

Measurement model is explicit: every metric declares level, category, source,
denominator/caveats, and instrumentation status. Missing data is reported as
unknown/not_instrumented; no synthetic numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

MEASUREMENT_LEVELS = (
    "business",
    "department",
    "process",
    "agent_team",
    "infra_resource",
)

KPI_CATEGORIES = (
    "commercial",
    "operational",
    "quality",
    "governance",
    "security",
    "privacy",
    "cost",
    "reliability",
)

METRIC_STATUSES = ("available", "partial", "unknown", "not_instrumented")

TARGET_DECISION_STATES = ("proposed", "baseline_required", "evidence_required", "ready_for_review")
TARGET_STATUSES = ("active", "review", "retired")
KPI_TARGETS_EXTRA_DATA_KEY = "kpi_targets"
KPI_TARGET_HISTORY_EXTRA_DATA_KEY = "kpi_target_history"
KPI_TARGET_HISTORY_MAX = 200
TARGET_PERSISTENCE = "org_extra_data"


def win_rate(closed_won: int, closed_lost: int) -> float:
    total = closed_won + closed_lost
    if total <= 0:
        return 0.0
    return round(closed_won / total, 4)


def conversion_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def average_deal_size(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    level: str
    category: str
    unit: str
    formula: str
    denominator: str
    source: str
    status: str
    owner: str
    caveats: tuple[str, ...] = ()
    balancing_metrics: tuple[str, ...] = ()
    anti_goodhart: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["caveats"] = list(self.caveats)
        data["balancing_metrics"] = list(self.balancing_metrics)
        data["anti_goodhart"] = list(self.anti_goodhart)
        return data


_CAVEAT_NOT_TARGET = "Not a target by itself; use with denominator/context and balancing metrics."
_CAVEAT_NO_BASELINE = "No target without measured baseline and evidence window."
_CAVEAT_TENANT = "Tenant-scoped; do not compare across orgs without normalization."


def _defs() -> list[MetricDefinition]:
    return [
        MetricDefinition(
            key="crm.win_rate",
            label="CRM Win Rate",
            level="business",
            category="commercial",
            unit="ratio",
            formula="closed_won / (closed_won + closed_lost)",
            denominator="closed_won + closed_lost",
            source="crm_deals",
            status="available",
            owner="sales",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT, "Zero denominator returns 0.0, not a win."),
            balancing_metrics=("crm.close_rate", "crm.average_deal_size"),
            anti_goodhart=("Pair with deal quality/margin; can be gamed by avoiding hard deals.",),
        ),
        MetricDefinition(
            key="crm.close_rate",
            label="CRM Close Rate",
            level="process",
            category="commercial",
            unit="ratio",
            formula="(closed_won + closed_lost) / pipeline_deals",
            denominator="pipeline_deals",
            source="crm_deals",
            status="available",
            owner="sales",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT),
            balancing_metrics=("crm.win_rate", "crm.pipeline_deals"),
            anti_goodhart=("Can be inflated by closing low-value deals; pair with average deal size.",),
        ),
        MetricDefinition(
            key="crm.average_deal_size",
            label="Average Won Deal Size",
            level="business",
            category="commercial",
            unit="currency",
            formula="sum(won_deal_value) / count(won_deals)",
            denominator="count(won_deals)",
            source="crm_deals",
            status="available",
            owner="sales",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT, "Currency/value quality depends on CRM input."),
            balancing_metrics=("crm.win_rate", "crm.close_rate"),
            anti_goodhart=("Can be gamed by cherry-picking large deals; pair with win rate.",),
        ),
        MetricDefinition(
            key="crm.pipeline_deals",
            label="Pipeline Deal Count",
            level="process",
            category="operational",
            unit="count",
            formula="count(crm_deals in scope)",
            denominator="n/a",
            source="crm_deals",
            status="available",
            owner="sales",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT),
            balancing_metrics=("crm.close_rate",),
            anti_goodhart=("Volume metric; do not use alone as performance target.",),
        ),
        MetricDefinition(
            key="governance.approval_latency_hours",
            label="Approval Latency",
            level="process",
            category="governance",
            unit="hours",
            formula="avg(decided_at - created_at) for decided pending_actions",
            denominator="decided pending_actions with timestamps",
            source="pending_actions",
            status="available",
            owner="governance",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT, "Computed only from decided actions with valid timestamps."),
            balancing_metrics=("governance.approval_rejection_rate", "security.incidents_open"),
            anti_goodhart=("Faster approvals can reduce control quality; pair with rejection/audit outcomes.",),
        ),
        MetricDefinition(
            key="governance.approval_rejection_rate",
            label="Approval Rejection Rate",
            level="process",
            category="governance",
            unit="ratio",
            formula="rejected / decided_pending_actions",
            denominator="decided pending_actions",
            source="pending_actions",
            status="available",
            owner="governance",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT),
            balancing_metrics=("governance.approval_latency_hours",),
            anti_goodhart=("High rejection may indicate bad proposals or overly strict gate; inspect reasons.",),
        ),
        MetricDefinition(
            key="governance.audit_events",
            label="Audit Events",
            level="business",
            category="governance",
            unit="count",
            formula="count(audit_logs)",
            denominator="n/a",
            source="audit_logs",
            status="available",
            owner="governance",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT, "Volume, not quality/compliance proof."),
            balancing_metrics=("governance.approval_rejection_rate",),
            anti_goodhart=("Can be inflated by noisy logging; do not reward raw volume.",),
        ),
        MetricDefinition(
            key="security.incidents_open",
            label="Open Security Incidents",
            level="business",
            category="security",
            unit="count",
            formula="count(security_incidents where status not closed/recovered)",
            denominator="n/a",
            source="security_incidents",
            status="partial",
            owner="security",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT, "Depends on incident reporting discipline."),
            balancing_metrics=("security.mttr_hours",),
            anti_goodhart=("Low count may mean under-reporting; pair with detection coverage.",),
        ),
        MetricDefinition(
            key="security.mttr_hours",
            label="Security MTTR",
            level="process",
            category="security",
            unit="hours",
            formula="avg(resolved_at/recovered_at/closed_at - detected_at)",
            denominator="resolved incidents with timestamps",
            source="security_incidents",
            status="partial",
            owner="security",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT, "Partial when timestamps missing."),
            balancing_metrics=("security.incidents_open",),
            anti_goodhart=("Can be gamed by closing early; pair with reopen/recurrence.",),
        ),
        MetricDefinition(
            key="privacy.requests_open",
            label="Open Privacy Requests",
            level="process",
            category="privacy",
            unit="count",
            formula="count(privacy_requests where status not completed/rejected)",
            denominator="n/a",
            source="privacy_requests",
            status="partial",
            owner="privacy",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT, "Depends on request intake workflow."),
            balancing_metrics=("privacy.request_completion_rate",),
            anti_goodhart=("Low count may indicate intake gaps.",),
        ),
        MetricDefinition(
            key="privacy.request_completion_rate",
            label="Privacy Request Completion Rate",
            level="process",
            category="privacy",
            unit="ratio",
            formula="completed / total_requests",
            denominator="total privacy requests",
            source="privacy_requests",
            status="partial",
            owner="privacy",
            caveats=(_CAVEAT_NOT_TARGET, _CAVEAT_TENANT),
            balancing_metrics=("privacy.requests_open",),
            anti_goodhart=("Can be gamed by rejecting requests; inspect rejection reasons.",),
        ),
        MetricDefinition(
            key="department.objective_attainment",
            label="Department Objective Attainment",
            level="department",
            category="operational",
            unit="ratio",
            formula="attained_objectives / declared_objectives",
            denominator="declared objectives with baseline+target",
            source="not_instrumented",
            status="not_instrumented",
            owner="department_lead",
            caveats=(_CAVEAT_NO_BASELINE, "No authoritative department objective store wired."),
            balancing_metrics=("process.on_time_completion",),
            anti_goodhart=("Do not set target before baseline and evidence.",),
        ),
        MetricDefinition(
            key="process.on_time_completion",
            label="Process On-Time Completion",
            level="process",
            category="operational",
            unit="ratio",
            formula="completed_on_time / completed_tasks",
            denominator="completed tasks with due dates",
            source="not_instrumented",
            status="not_instrumented",
            owner="operations",
            caveats=(_CAVEAT_NO_BASELINE, "Due-date/SLA instrumentation not authoritative."),
            balancing_metrics=("quality.defect_escape_rate",),
            anti_goodhart=("Speed target can harm quality; pair with quality metric.",),
        ),
        MetricDefinition(
            key="agent_team.task_success_rate",
            label="Agent Team Task Success Rate",
            level="agent_team",
            category="quality",
            unit="ratio",
            formula="successful_tasks / assigned_tasks",
            denominator="assigned tasks with outcome labels",
            source="not_instrumented",
            status="not_instrumented",
            owner="agent_ops",
            caveats=(_CAVEAT_NO_BASELINE, "Outcome labels not uniformly instrumented."),
            balancing_metrics=("cost.per_successful_task",),
            anti_goodhart=("Can be gamed by selecting easy tasks.",),
        ),
        MetricDefinition(
            key="infra_resource.cost_per_1k_tokens",
            label="Cost per 1K Tokens",
            level="infra_resource",
            category="cost",
            unit="currency_per_1k_tokens",
            formula="total_cost / (tokens / 1000)",
            denominator="tokens > 0",
            source="not_instrumented",
            status="not_instrumented",
            owner="platform",
            caveats=(_CAVEAT_NO_BASELINE, "Authoritative token-cost attribution not wired in KPI catalog."),
            balancing_metrics=("quality.defect_escape_rate",),
            anti_goodhart=("Cheapness can degrade quality; pair with quality/outcome.",),
        ),
    ]


def kpi_catalog(*, level: str | None = None, category: str | None = None) -> dict[str, Any]:
    defs = _defs()
    if level:
        defs = [d for d in defs if d.level == level]
    if category:
        defs = [d for d in defs if d.category == category]
    return {
        "measurement_model": {
            "levels": list(MEASUREMENT_LEVELS),
            "categories": list(KPI_CATEGORIES),
            "statuses": list(METRIC_STATUSES),
            "principles": [
                "No fake metrics: unavailable data is unknown/not_instrumented.",
                "Every KPI includes denominator/context/caveats.",
                "No target without baseline and evidence.",
                "Balancing metrics required for Goodhart-sensitive targets.",
            ],
        },
        "metrics": [d.as_dict() for d in defs],
        "count": len(defs),
    }


def _status(value: Any, *, available: bool, partial: bool = False) -> str:
    if not available:
        return "unknown"
    if partial:
        return "partial"
    return "available"


def _metric_value(defn: MetricDefinition, value: Any, *, status: str, denominator_value: Any = None, context: dict | None = None) -> dict[str, Any]:
    ctx = {"denominator": defn.denominator, "denominator_value": denominator_value}
    if context:
        ctx.update(context)
    return {
        **defn.as_dict(),
        "value": value,
        "status": status,
        "context": ctx,
        "target_policy": {
            "can_set_target": False,
            "reason": "Target requires baseline window and evidence before governance approval.",
        },
    }


def _safe_div(num: float, den: float) -> float | None:
    if den <= 0:
        return None
    return round(num / den, 4)


def governance_kpis_snapshot(*, audit_count: int | None, decided_approvals: int | None, rejected_approvals: int | None,
                             approval_latency_hours: float | None, open_incidents: int | None, mttr_hours: float | None,
                             open_privacy_requests: int | None, privacy_completion_rate: float | None,
                             sources: dict[str, str] | None = None) -> dict[str, Any]:
    defs = {d.key: d for d in _defs()}
    src = sources or {}
    metrics = []

    rej_rate = _safe_div(float(rejected_approvals or 0), float(decided_approvals or 0)) if decided_approvals is not None else None
    metrics.append(_metric_value(
        defs["governance.audit_events"], audit_count,
        status=_status(audit_count, available=audit_count is not None),
        denominator_value=None, context={"source_table": src.get("audit_logs", "audit_logs")},
    ))
    metrics.append(_metric_value(
        defs["governance.approval_latency_hours"], approval_latency_hours,
        status=_status(approval_latency_hours, available=approval_latency_hours is not None),
        denominator_value=decided_approvals,
        context={"source_table": src.get("pending_actions", "pending_actions"), "decided_actions": decided_approvals},
    ))
    metrics.append(_metric_value(
        defs["governance.approval_rejection_rate"], rej_rate,
        status=_status(rej_rate, available=decided_approvals is not None),
        denominator_value=decided_approvals,
        context={"source_table": src.get("pending_actions", "pending_actions"), "rejected_actions": rejected_approvals},
    ))
    metrics.append(_metric_value(
        defs["security.incidents_open"], open_incidents,
        status=_status(open_incidents, available=open_incidents is not None, partial=open_incidents is not None),
        denominator_value=None, context={"source_table": src.get("security_incidents", "security_incidents")},
    ))
    metrics.append(_metric_value(
        defs["security.mttr_hours"], mttr_hours,
        status=_status(mttr_hours, available=mttr_hours is not None, partial=mttr_hours is not None),
        denominator_value=None, context={"source_table": src.get("security_incidents", "security_incidents")},
    ))
    metrics.append(_metric_value(
        defs["privacy.requests_open"], open_privacy_requests,
        status=_status(open_privacy_requests, available=open_privacy_requests is not None, partial=open_privacy_requests is not None),
        denominator_value=None, context={"source_table": src.get("privacy_requests", "privacy_requests")},
    ))
    metrics.append(_metric_value(
        defs["privacy.request_completion_rate"], privacy_completion_rate,
        status=_status(privacy_completion_rate, available=privacy_completion_rate is not None, partial=privacy_completion_rate is not None),
        denominator_value=None, context={"source_table": src.get("privacy_requests", "privacy_requests")},
    ))

    unavailable = [m["key"] for m in metrics if m["status"] in {"unknown", "not_instrumented"}]
    return {
        "category": "governance",
        "metrics": metrics,
        "unavailable": unavailable,
        "guardrails": {
            "no_fake_metrics": True,
            "targets_require_baseline_and_evidence": True,
            "balancing_metrics_required": True,
            "not_a_target_by_itself": _CAVEAT_NOT_TARGET,
        },
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_target_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, dict)]


def _target_store(extra_data: dict | None) -> dict[str, Any]:
    data = extra_data if isinstance(extra_data, dict) else {}
    raw = data.get(KPI_TARGETS_EXTRA_DATA_KEY)
    store = raw if isinstance(raw, dict) else {}
    return {
        "version": 1,
        "persistence": TARGET_PERSISTENCE,
        "targets": _clean_target_list(store.get("targets")),
    }


def _target_history(extra_data: dict | None) -> list[dict[str, Any]]:
    data = extra_data if isinstance(extra_data, dict) else {}
    return _clean_target_list(data.get(KPI_TARGET_HISTORY_EXTRA_DATA_KEY))


def _append_target_history(extra_data: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
    history = _target_history(extra_data)
    history.append(event)
    if len(history) > KPI_TARGET_HISTORY_MAX:
        history = history[-KPI_TARGET_HISTORY_MAX:]
    extra_data[KPI_TARGET_HISTORY_EXTRA_DATA_KEY] = history
    return history


def list_kpi_targets(extra_data: dict | None) -> dict[str, Any]:
    store = _target_store(extra_data)
    targets = sorted(store["targets"], key=lambda t: str(t.get("updated_at") or ""), reverse=True)
    history = _target_history(extra_data)
    return {
        "persistence": TARGET_PERSISTENCE,
        "storage": f"Organization.extra_data[{KPI_TARGETS_EXTRA_DATA_KEY}]",
        "history_storage": f"Organization.extra_data[{KPI_TARGET_HISTORY_EXTRA_DATA_KEY}]",
        "schema_table": None,
        "targets": targets,
        "count": len(targets),
        "history_count": len(history),
        "guardrails": {
            "no_fake_metrics": True,
            "no_target_without_baseline": True,
            "no_target_without_evidence": True,
            "balancing_metrics_required": True,
            "not_a_target_by_itself": _CAVEAT_NOT_TARGET,
        },
    }


def validate_target_proposal(
    *,
    metric_key: str,
    target_value: float | int | None,
    baseline_value: float | int | None,
    baseline_window_days: int | None,
    evidence: str | None = None,
    owner: str | None = None,
    balancing_metrics: list[str] | None = None,
) -> dict[str, Any]:
    defs = {d.key: d for d in _defs()}
    defn = defs.get(metric_key)
    if defn is None:
        return {
            "ok": False,
            "state": "rejected",
            "metric_key": metric_key,
            "errors": ["unknown metric_key; use catalog"],
        }

    errors: list[str] = []
    warnings: list[str] = []
    if target_value is None:
        errors.append("target_value required")
    if baseline_value is None:
        errors.append("baseline_value required; no target before baseline")
    if not baseline_window_days or baseline_window_days <= 0:
        errors.append("baseline_window_days > 0 required")
    if not evidence or not str(evidence).strip():
        errors.append("evidence required (query, report, incident log, or audit reference)")
    if not owner or not str(owner).strip():
        errors.append("owner required")

    bms = [m for m in (balancing_metrics or []) if isinstance(m, str) and m.strip()]
    required_bms = list(defn.balancing_metrics)
    if required_bms and not bms:
        errors.append(f"balancing_metrics required: {required_bms}")
    unknown_bms = [m for m in bms if m not in defs]
    if unknown_bms:
        errors.append(f"unknown balancing_metrics: {unknown_bms}")
    if defn.key in bms:
        errors.append("balancing_metrics must not include the target metric itself")

    if defn.status == "not_instrumented":
        errors.append("metric not_instrumented; cannot set target until instrumented")

    state = "ready_for_review" if not errors else (
        "baseline_required" if baseline_value is None else "evidence_required"
    )
    return {
        "ok": not errors,
        "state": state,
        "metric": defn.as_dict(),
        "proposal": {
            "metric_key": metric_key,
            "target_value": target_value,
            "baseline_value": baseline_value,
            "baseline_window_days": baseline_window_days,
            "evidence": str(evidence).strip() if evidence else evidence,
            "owner": str(owner).strip() if owner else owner,
            "balancing_metrics": bms,
        },
        "errors": errors,
        "warnings": warnings,
        "persistence": {
            "persisted": False,
            "mode": TARGET_PERSISTENCE,
            "schema_table": None,
            "blocker": None if not errors else "Target invalid; persistence refused (fail closed).",
        },
        "guardrails": {
            "no_target_without_baseline": True,
            "no_target_without_evidence": True,
            "balancing_metrics_required": bool(required_bms),
            "not_a_target_by_itself": _CAVEAT_NOT_TARGET,
        },
    }


def set_kpi_target(
    *,
    extra_data: dict | None,
    metric_key: str,
    target_value: float | int | None,
    baseline_value: float | int | None,
    baseline_window_days: int | None,
    evidence: str | None = None,
    owner: str | None = None,
    balancing_metrics: list[str] | None = None,
    status: str | None = None,
    actor_user_id: str | None = None,
    actor_org_id: str | None = None,
) -> dict[str, Any]:
    validation = validate_target_proposal(
        metric_key=metric_key,
        target_value=target_value,
        baseline_value=baseline_value,
        baseline_window_days=baseline_window_days,
        evidence=evidence,
        owner=owner,
        balancing_metrics=balancing_metrics,
    )
    if not validation["ok"]:
        return {
            **validation,
            "persistence": {
                "persisted": False,
                "mode": TARGET_PERSISTENCE,
                "schema_table": None,
                "blocker": "Validation failed; target not persisted (fail closed).",
            },
        }

    desired_status = str(status or "active").strip().lower()
    if desired_status not in TARGET_STATUSES:
        return {
            **validation,
            "ok": False,
            "state": "rejected",
            "errors": [f"invalid status; allowed: {list(TARGET_STATUSES)}"],
            "persistence": {
                "persisted": False,
                "mode": TARGET_PERSISTENCE,
                "schema_table": None,
                "blocker": "Invalid status; target not persisted (fail closed).",
            },
        }

    data = dict(extra_data) if isinstance(extra_data, dict) else {}
    store = _target_store(data)
    now = _now_iso()
    targets = list(store["targets"])
    existing = next((t for t in targets if t.get("metric_key") == metric_key), None)
    previous_status = (existing or {}).get("status")
    record = {
        "id": (existing or {}).get("id") or str(uuid4()),
        "metric_key": metric_key,
        "target_value": target_value,
        "baseline_value": baseline_value,
        "baseline_window_days": int(baseline_window_days),
        "evidence": str(evidence).strip(),
        "owner": str(owner).strip(),
        "balancing_metrics": list(validation["proposal"]["balancing_metrics"]),
        "status": desired_status,
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
        "provenance": {
            "actor_user_id": actor_user_id,
            "actor_org_id": actor_org_id,
            "source": "api.analytics.kpi.targets.set",
            "validation_state": validation["state"],
        },
        "guardrails": {
            "no_target_without_baseline": True,
            "no_target_without_evidence": True,
            "balancing_metrics_required": bool(validation["metric"]["balancing_metrics"]),
            "not_a_target_by_itself": _CAVEAT_NOT_TARGET,
        },
    }
    if existing:
        targets = [record if t.get("metric_key") == metric_key else t for t in targets]
        event_type = "target_updated"
    else:
        targets.append(record)
        event_type = "target_created"
    data[KPI_TARGETS_EXTRA_DATA_KEY] = {
        "version": 1,
        "persistence": TARGET_PERSISTENCE,
        "targets": targets,
    }
    history = _append_target_history(data, {
        "id": str(uuid4()),
        "event": event_type,
        "metric_key": metric_key,
        "target_id": record["id"],
        "from_status": previous_status,
        "to_status": desired_status,
        "actor_user_id": actor_user_id,
        "actor_org_id": actor_org_id,
        "at": now,
        "evidence": record["evidence"],
        "owner": record["owner"],
        "target_value": target_value,
        "baseline_value": baseline_value,
    })
    return {
        **validation,
        "persistence": {
            "persisted": True,
            "mode": TARGET_PERSISTENCE,
            "schema_table": None,
            "storage": f"Organization.extra_data[{KPI_TARGETS_EXTRA_DATA_KEY}]",
            "history_storage": f"Organization.extra_data[{KPI_TARGET_HISTORY_EXTRA_DATA_KEY}]",
        },
        "target": record,
        "history_count": len(history),
        "extra_data": data,
    }


def list_kpi_target_history(extra_data: dict | None, *, metric_key: str | None = None) -> dict[str, Any]:
    history = _target_history(extra_data)
    if metric_key:
        history = [h for h in history if h.get("metric_key") == metric_key]
    history = sorted(history, key=lambda h: str(h.get("at") or ""), reverse=True)
    return {
        "persistence": TARGET_PERSISTENCE,
        "storage": f"Organization.extra_data[{KPI_TARGET_HISTORY_EXTRA_DATA_KEY}]",
        "schema_table": None,
        "history": history,
        "count": len(history),
        "max_entries": KPI_TARGET_HISTORY_MAX,
    }


def transition_kpi_target_status(
    *,
    extra_data: dict | None,
    metric_key: str,
    status: str,
    evidence: str | None = None,
    actor_user_id: str | None = None,
    actor_org_id: str | None = None,
) -> dict[str, Any]:
    desired = str(status or "").strip().lower()
    if desired not in TARGET_STATUSES:
        return {
            "ok": False,
            "state": "rejected",
            "metric_key": metric_key,
            "errors": [f"invalid status; allowed: {list(TARGET_STATUSES)}"],
            "persistence": {"persisted": False, "mode": TARGET_PERSISTENCE, "schema_table": None},
        }
    data = dict(extra_data) if isinstance(extra_data, dict) else {}
    store = _target_store(data)
    targets = list(store["targets"])
    existing = next((t for t in targets if t.get("metric_key") == metric_key), None)
    if not existing:
        return {
            "ok": False,
            "state": "rejected",
            "metric_key": metric_key,
            "errors": ["target not found; set target before transition"],
            "persistence": {"persisted": False, "mode": TARGET_PERSISTENCE, "schema_table": None},
        }

    ev = str(evidence).strip() if evidence else ""
    if not ev:
        return {
            "ok": False,
            "state": "evidence_required",
            "metric_key": metric_key,
            "errors": ["evidence required for status transition"],
            "persistence": {"persisted": False, "mode": TARGET_PERSISTENCE, "schema_table": None},
        }

    now = _now_iso()
    previous_status = existing.get("status")
    record = dict(existing)
    record["status"] = desired
    record["updated_at"] = now
    prov = dict(record.get("provenance") or {})
    prov.update({
        "actor_user_id": actor_user_id,
        "actor_org_id": actor_org_id,
        "source": "api.analytics.kpi.targets.transition",
        "last_transition_evidence": ev,
    })
    record["provenance"] = prov
    targets = [record if t.get("metric_key") == metric_key else t for t in targets]
    data[KPI_TARGETS_EXTRA_DATA_KEY] = {
        "version": 1,
        "persistence": TARGET_PERSISTENCE,
        "targets": targets,
    }
    history = _append_target_history(data, {
        "id": str(uuid4()),
        "event": "status_transition",
        "metric_key": metric_key,
        "target_id": record.get("id"),
        "from_status": previous_status,
        "to_status": desired,
        "actor_user_id": actor_user_id,
        "actor_org_id": actor_org_id,
        "at": now,
        "evidence": ev,
        "owner": record.get("owner"),
        "target_value": record.get("target_value"),
        "baseline_value": record.get("baseline_value"),
    })
    return {
        "ok": True,
        "state": "ready_for_review",
        "metric_key": metric_key,
        "target": record,
        "history_count": len(history),
        "persistence": {
            "persisted": True,
            "mode": TARGET_PERSISTENCE,
            "schema_table": None,
            "storage": f"Organization.extra_data[{KPI_TARGETS_EXTRA_DATA_KEY}]",
            "history_storage": f"Organization.extra_data[{KPI_TARGET_HISTORY_EXTRA_DATA_KEY}]",
        },
        "extra_data": data,
    }


def interpret_kpis(current: dict[str, float], previous: dict[str, float] | None = None) -> dict:
    """Deterministic narrative over authoritative KPIs; no invented targets.

    Comparisons use the caller's baseline only. An LLM may paraphrase this
    output but must not originate the numbers or the direction.
    """
    previous = previous or {}
    items = []
    declines = []
    for name in sorted(current):
        now = float(current[name])
        if name in previous and float(previous[name]) > 0:
            before = float(previous[name])
            delta = round(now - before, 4)
            direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
            items.append(f"{name}: {now:g} ({direction} {abs(delta):g} vs baseline)")
            if delta < 0:
                declines.append((name, delta / before))
        else:
            items.append(f"{name}: {now:g} (no baseline)")
    watch = min(declines, key=lambda pair: pair[1])[0] if declines else None
    summary = "; ".join(items) if items else "no KPI values"
    if watch:
        summary += f". Largest relative decline: {watch}."
    return {
        "summary": summary,
        "items": items,
        "watch": watch,
        "guardrails": {
            "baseline_only": True,
            "no_invented_targets": True,
            "not_a_target_by_itself": _CAVEAT_NOT_TARGET,
        },
    }
