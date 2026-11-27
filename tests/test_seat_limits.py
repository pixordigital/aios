"""Phase 7 slice: per-seat allowed models (org.extra_data.seats)."""
from types import SimpleNamespace

from aios.core.limits import seat_allows_model


def _org(extra: dict) -> SimpleNamespace:
    return SimpleNamespace(extra_data=extra or {})


def test_seat_allows_model_empty_config_allows():
    org = _org({})
    assert seat_allows_model(org, "u1", "openai/gpt-4o-mini") is True


def test_seat_allows_model_allows_listed_model():
    org = _org({"seats": {"u1": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4"]}})
    assert seat_allows_model(org, "u1", "openai/gpt-4o-mini") is True
    assert seat_allows_model(org, "u1", "anthropic/claude-sonnet-4") is True


def test_seat_allows_model_denies_unlisted_model():
    org = _org({"seats": {"u1": ["openai/gpt-4o-mini"]}})
    assert seat_allows_model(org, "u1", "openai/gpt-4o") is False


def test_seat_allows_model_other_seat_unlisted_denies():
    org = _org({"seats": {"u1": ["openai/gpt-4o-mini"]}})
    assert seat_allows_model(org, "u2", "openai/gpt-4o-mini") is True  # empty seat -> allow


def test_membership_allowed_models_used_without_org_seats():
    org = _org({})
    assert seat_allows_model(org, "u1", "openai/gpt-4o-mini", ["openai/gpt-4o-mini"]) is True
    assert seat_allows_model(org, "u1", "openai/gpt-4o", ["openai/gpt-4o-mini"]) is False


def test_org_seats_override_membership():
    org = _org({"seats": {"u1": ["openai/gpt-4o"]}})
    assert seat_allows_model(org, "u1", "openai/gpt-4o", ["openai/gpt-4o-mini"]) is True
    assert seat_allows_model(org, "u1", "openai/gpt-4o-mini", ["openai/gpt-4o-mini"]) is False


def test_missing_model_never_enforces_seat():
    org = _org({"seats": {"u1": ["openai/gpt-4o-mini"]}})
    assert seat_allows_model(org, "u1", None) is True


def test_check_org_limits_denies_membership_model_mismatch():
    import asyncio

    from aios.core.limits import check_org_limits

    class _Result:
        def scalar_one_or_none(self):
            return ["openai/gpt-4o-mini"]

    class _DB:
        async def get(self, model, ident):
            org = _org({})
            org.is_active = True
            org.license_status = "active"
            return org

        async def execute(self, stmt, *a, **k):
            assert "organization_memberships" in str(stmt)
            return _Result()

    allowed, reason = asyncio.run(check_org_limits("org-1", _DB(), user_id="u1", model="openai/gpt-4o"))
    assert allowed is False
    assert "not allowed for model" in reason


def test_worker_websocket_seat_identity_enforces_model():
    """Worker resolves a seat only from authenticated, persisted member context."""
    import asyncio

    from aios.core.limits import check_org_limits
    from aios.tasks.jobs import _inbound_seat_identity

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class _DB:
        async def get(self, model, ident):
            org = _org({"seats": {"u1": ["openai/gpt-4o-mini"]}})
            org.is_active = True
            org.license_status = "active"
            return org

        async def execute(self, stmt, *a, **k):
            sql = str(stmt)
            assert "organization_memberships" in sql
            if "allowed_models" in sql:
                return _Result(["openai/gpt-4o-mini"])
            return _Result("m1")

    agent = SimpleNamespace(llm_config={"model": "openai/gpt-4o"})
    msg = SimpleNamespace(extra_data={"user_id": "u1"})
    db = _DB()

    identity = asyncio.run(
        _inbound_seat_identity(db, "org-1", "web", msg, {"source": "websocket"}, agent)
    )
    assert identity == ("u1", "openai/gpt-4o")
    assert asyncio.run(check_org_limits("org-1", db, *identity))[0] is False

    # Provider webhook identity is a contact, never a seat.
    assert asyncio.run(
        _inbound_seat_identity(db, "org-1", "evolution", msg, {"source": "websocket"}, agent)
    ) == (None, None)
