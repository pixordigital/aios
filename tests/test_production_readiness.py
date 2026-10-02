"""Regression tests for the production-readiness audit fixes.

Each test here pins a specific defect that was live in production. They are
written to fail if the fix is reverted, not to assert general policy.
"""

import inspect
import pathlib

import pytest
from sqlalchemy import inspect as sa_inspect

from aios.api import approvals as approvals_mod
from aios.api import auth as auth_mod
from aios.core import delivery, limits
from aios.db.models import AgentMetric, PendingAction

ROOT = pathlib.Path(__file__).resolve().parents[1]


def template_code(path: str) -> str:
    """Template body with {#- ... -#} comments removed.

    Several fixes document the old defect in a comment; asserting against the raw
    file would then match the explanation rather than the code.
    """
    import re

    raw = (ROOT / path).read_text(encoding="utf-8")
    return re.sub(r"\{#-?.*?-?#\}", "", raw, flags=re.S)


# ── tenant isolation on the approval queue ───────────────────────────────

def test_pending_action_has_org_id():
    """The approvals queue was org-blind because the column did not exist."""
    assert hasattr(PendingAction, "org_id"), (
        "PendingAction.org_id was removed -- every approvals query depends on it"
    )


def test_approvals_list_is_org_scoped():
    src = inspect.getsource(approvals_mod)
    assert "DBAction.org_id == org_id" in src, (
        "GET /api/approvals must filter pending_actions by org_id"
    )


def test_approval_decisions_pass_org_id():
    """approve/reject used to write cross-tenant via an unscoped fallback."""
    src = inspect.getsource(approvals_mod)
    assert "approve(action_id, decided_by=user.id, org_id=user.org_id)" in src
    assert "reject(action_id, decided_by=user.id, org_id=user.org_id)" in src


def test_approve_refuses_cross_org_in_memory_row():
    """approve() reported 404 but still wrote the other tenant's row."""
    from aios.core.approval import approval_manager

    approval_manager._pending.clear()
    pa = PendingAction(
        id="act-cross-org",
        org_id="org-VICTIM",
        agent_id="a",
        conversation_id="c",
        tool_name="t",
        tool_args={},
    )
    approval_manager._pending["act-cross-org"] = pa
    assert approval_manager.approve("act-cross-org", org_id="org-ATTACKER") is False
    # status defaults are applied at flush, so only assert it was NOT approved
    assert pa.status != "approved", "cross-org approve must not mutate the row"
    approval_manager._pending.clear()


# ── unauthenticated dashboard leak ────────────────────────────────────────

def test_dashboard_root_is_not_auth_exempt():
    """/dashboard/ skipped auth entirely and fell back to the owner org."""
    from aios.main import AUTH_EXEMPT

    assert "/dashboard/" not in AUTH_EXEMPT, (
        "/dashboard/ must not be exempt -- the trailing-slash route rendered the "
        "operator org's agents, teams and spend to anonymous callers"
    )


# ── fail-closed webhooks ──────────────────────────────────────────────────

def test_slack_webhook_fails_closed_without_secret():
    src = (ROOT / "aios/api/slack_webhook.py").read_text(encoding="utf-8")
    assert "return True  # No secret configured" not in src
    assert "refusing unauthenticated webhook" in src, (
        "an unconfigured Slack webhook must reject, not authenticate everyone"
    )


def test_voice_webhook_fails_closed_without_secret():
    src = (ROOT / "aios/api/voice_webhook.py").read_text(encoding="utf-8")
    assert "refusing unauthenticated webhook" in src, (
        "forged Twilio events could trigger agent runs and bill usage"
    )


# ── WhatsApp guard must not fail open ────────────────────────────────────

def test_delivery_guard_failure_does_not_send():
    """A guard error used to fall through and deliver anyway."""
    src = inspect.getsource(delivery.deliver_message)
    guard_try = src.index("guard_send")
    handler = src[guard_try:guard_try + 4000]
    except_idx = handler.index("except Exception:")
    block = handler[except_idx:except_idx + 1200]
    assert "refusing to send" in block and "return" in block, (
        "guard failure must abort the send (opt-out / ban protection), not pass it"
    )


# ── idempotent outbound ───────────────────────────────────────────────────

def test_outbound_idempotency_key_excludes_attempt():
    """Including the attempt gave every retry a different key."""
    src = inspect.getsource(delivery.deliver_message)
    key_block = src[src.index("idempotency_key = _h.sha256"):][:300]
    assert "|{attempt}" not in key_block and "|{attempt}" not in src.split("idempotency_key = _h.sha256")[1][:200], (
        "the key must NOT include the attempt number or retries can never dedupe"
    )


def test_retry_reuses_the_same_idempotency_key():
    src = inspect.getsource(delivery.deliver_message)
    assert "idempotency_key,  # same logical send" in src


# ── inbound retry must not silently swallow the message ───────────────────

def test_inbound_dedup_only_skips_completed_attempts():
    src = (ROOT / "aios/tasks/jobs.py").read_text(encoding="utf-8")
    assert 'dup.extra_data or {}).get("inbound_completed")' in src, (
        "dedup must check inbound_completed, or a retry after a failed agent run "
        "returns success and the customer message is lost with no DLQ entry"
    )
    assert "inbound_completed" in src


# ── quota locking actually locks ─────────────────────────────────────────

def test_is_sqlite_is_awaited():
    """A coroutine is truthy, so the missing await disabled FOR UPDATE."""
    src = (ROOT / "aios/core/limits.py").read_text(encoding="utf-8")
    assert '"" if await _is_sqlite(db) else " FOR UPDATE"' in src


# ── licensing is enforced, not just written ──────────────────────────────

def test_license_status_is_enforced():
    src = (ROOT / "aios/core/limits.py").read_text(encoding="utf-8")
    assert "license_status" in src, (
        "license_status was written by the anti-tamper control and read nowhere"
    )


# ── telemetry correctness ─────────────────────────────────────────────────

def test_agent_metric_has_unique_agent_hour():
    """Duplicate rows made scalar_one_or_none() fail forever, silently."""
    names = {c.name for c in AgentMetric.__table__.constraints
             if c.__class__.__name__ == "UniqueConstraint"}
    assert "uq_agent_metrics_agent_hour" in names


def test_agent_metric_tracks_samples():
    """(avg + dur) / 2 is the mean only at n == 2."""
    assert hasattr(AgentMetric, "samples")


def test_metrics_use_atomic_upsert():
    src = (ROOT / "aios/core/tracing.py").read_text(encoding="utf-8")
    assert "on_conflict_do_update" in src, "metric write must be an atomic upsert"


# ── traces cannot OOM the container ──────────────────────────────────────

def test_traces_dict_is_bounded():
    src = (ROOT / "aios/core/tracing.py").read_text(encoding="utf-8")
    assert "TRACES_MAX" in src and "pop(_old" in src


# ── secure defaults ──────────────────────────────────────────────────────

def test_debug_defaults_to_false():
    from aios.config import Settings

    assert Settings(_env_file=None).debug is False, (
        "debug=True disabled rate limiting and enabled wildcard CORS with credentials"
    )


# ── deploy layer must see migration failures ─────────────────────────────

def test_entrypoint_does_not_pipe_alembic_through_tee():
    """`alembic | tee` reports tee's exit status, so failure was invisible."""
    src = (ROOT / "deploy/entrypoint.sh").read_text(encoding="utf-8")
    assert "| tee" not in src, (
        "piping alembic through tee makes every guard unreachable; a failed "
        "migration currently starts the app against a half-migrated schema"
    )
    assert "Refusing to start" in src
    assert "alembic stamp head" in src, (
        "a database created by create_all has no alembic_version; replaying the "
        "chain must stamp head rather than crash-loop the container"
    )


def test_healthcheck_stays_liveness_only():
    """Docker HEALTHCHECK must not use readiness.

    /health/ready 503s until Postgres, Redis and RAG are warm, and Coolify
    restarts any container it marks unhealthy. Pointing HEALTHCHECK at readiness
    therefore produced a restart loop that took production down. Readiness is for
    the proxy/routing decision, liveness for the restart decision.
    """
    for f in ("Dockerfile", "docker-compose.coolify.yml"):
        src = (ROOT / f).read_text(encoding="utf-8")
        assert "/health/ready" not in src, (
            f"{f}: HEALTHCHECK on /health/ready causes an unhealthy-restart loop"
        )
        assert "/health/live" in src


# ── migration chain actually completes ───────────────────────────────────

def test_no_duplicate_column_adds_in_migration_chain():
    """g3a4b5c6d7e8 re-added columns 9051a2b3c4d9 already created, aborting at 15/30."""
    src = (ROOT / "alembic/versions/g3a4b5c6d7e8_add_workflow_node_failure_handling.py").read_text(
        encoding="utf-8"
    )
    assert "_existing_columns" in src and 'if "on_failure" not in present' in src


def test_duplicate_migrations_tree_removed():
    assert not (ROOT / "migrations").exists(), (
        "migrations/ duplicated alembic/ with colliding revision ids"
    )


# ── guard against the specific regression this audit introduced ──────────

def test_dashboard_pending_action_queries_reference_real_column():
    """A PendingAction.org_id filter against a missing column 500s the CRM page."""
    src = (ROOT / "aios/dashboard/app.py").read_text(encoding="utf-8")
    if "PendingAction.org_id" in src:
        cols = {c.name for c in PendingAction.__table__.columns}
        assert "org_id" in cols, (
            "dashboard queries filter on PendingAction.org_id but the column is gone"
        )


def test_crm_board_columns_come_from_data():
    """A hardcoded 6-stage ladder hid deals in other stages from the board."""
    code = template_code("aios/dashboard/templates/crm.html")
    assert "repeat(6,1fr)" not in code, "board grid must size itself from the data"
    assert "{% for stage in ordered %}" in code


def test_billing_roi_is_not_fabricated():
    code = template_code("aios/dashboard/templates/billing.html")
    assert "total_tokens / 800" not in code, (
        "conversations were invented as tokens/800 and shown as a measured metric"
    )
    roi_tail = code.split("ROI</div>")[0][-400:]
    assert "∞" not in roi_tail, "ROI must not render as infinity"
    assert "conversas" not in code, "the fabricated conversation count must be gone"


def test_sandbox_blocks_ctypes_and_os():
    """The sandbox was full RCE via `import os` / ctypes."""
    from aios.core.sandbox import validate_code

    assert validate_code("import ctypes\nprint(ctypes.CDLL(None).system('id'))")
    assert validate_code("import os\nprint(os.getcwd())")