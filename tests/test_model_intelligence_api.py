"""Model Intelligence API: fail-closed eligibility, evidence-backed proposals, Founder approval."""

from aios.db.models import Organization
from aios.governance.model_intelligence import ModelRegistryEntry


async def _create(auth_client, key, **extra):
    body = {
        "model_key": key,
        "provider": "openrouter",
        "price_currency": "USD",
        "quality_score": 0.9,
        "reliability": 1.0,
        "capabilities": ["chat"],
        "context_window": 8000,
        **extra,
    }
    resp = await auth_client.post("/api/models", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _founder(test_db_session, test_org, test_user):
    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()


async def test_registry_approval_eligibility_and_selection(
    auth_client, test_db_session, test_org, test_user
):
    expensive = await _create(auth_client, "expensive", input_price_per_1m=10.0)
    cheap = await _create(auth_client, "cheap", input_price_per_1m=5.0, quality_score=0.8)

    resp = await auth_client.post(f"/api/models/{cheap}/approve")
    assert resp.status_code == 403  # admin is not Founder
    await _founder(test_db_session, test_org, test_user)
    for mid in (expensive, cheap):
        resp = await auth_client.post(f"/api/models/{mid}/approve")
        assert resp.status_code == 200, resp.text

    ids = {m["id"] for m in (await auth_client.get("/api/models")).json()["items"]}
    assert {expensive, cheap} <= ids

    resp = await auth_client.post(
        "/api/models/eligible", json={"required_capabilities": ["chat"]}
    )
    assert set(resp.json()["items"]) == {"cheap", "expensive"}

    resp = await auth_client.post(
        "/api/models/select",
        json={"avg_input_tokens": 1_000_000, "avg_output_tokens": 0, "required_capabilities": ["chat"]},
    )
    assert resp.json()["model_key"] == "cheap"
    assert resp.json()["cost_per_success"] == 5.0


async def test_fail_closed_filters(auth_client, test_db_session, test_org, test_user):
    await _create(auth_client, "unapproved", input_price_per_1m=1.0)
    restricted = await _create(auth_client, "restricted", input_price_per_1m=1.0, privacy_ok=False)
    wrong_currency = await _create(auth_client, "euro", input_price_per_1m=1.0, price_currency="EUR")
    await _founder(test_db_session, test_org, test_user)
    for mid in (restricted, wrong_currency):
        assert (await auth_client.post(f"/api/models/{mid}/approve")).status_code == 200

    resp = await auth_client.post("/api/models/eligible", json={})
    assert resp.json()["items"] == []  # unapproved + privacy fail + currency mismatch

    resp = await auth_client.post(
        "/api/models/select", json={"avg_input_tokens": 1000, "avg_output_tokens": 0}
    )
    assert resp.json() == {"model_key": None, "cost_per_success": None}


async def test_recommendation_and_rollback(auth_client, test_db_session, test_org, test_user):
    current = await _create(auth_client, "current", input_price_per_1m=10.0, quality_score=0.9)
    proposed = await _create(auth_client, "proposed", input_price_per_1m=5.0, quality_score=0.8)
    low_quality = await _create(auth_client, "low-quality", input_price_per_1m=1.0, quality_score=0.5)
    await _founder(test_db_session, test_org, test_user)
    for mid in (current, proposed, low_quality):
        assert (await auth_client.post(f"/api/models/{mid}/approve")).status_code == 200

    resp = await auth_client.post(
        "/api/models/recommend",
        json={
            "current_model_key": "current", "proposed_model_key": "proposed",
            "avg_input_tokens": 1_000_000, "avg_output_tokens": 0,
            "monthly_tasks": 100, "required_quality": 0.7,
        },
    )
    assert resp.json()["recommended"] is True
    assert resp.json()["expected_monthly_savings"] == 500.0
    assert resp.json()["requires_founder_approval"] is True

    resp = await auth_client.post(
        "/api/models/recommend",
        json={
            "current_model_key": "current", "proposed_model_key": "low-quality",
            "avg_input_tokens": 1_000_000, "avg_output_tokens": 0,
            "monthly_tasks": 100, "required_quality": 0.7,
        },
    )
    assert resp.json()["recommended"] is False

    resp = await auth_client.get(
        "/api/models/rollback-target",
        params={"agent_default_key": "current", "previous_key": "proposed"},
    )
    assert resp.json()["model_key"] == "proposed"
    resp = await auth_client.get(
        "/api/models/rollback-target",
        params={"agent_default_key": "current", "previous_key": "missing"},
    )
    assert resp.json()["model_key"] == "current"


async def test_models_are_tenant_scoped(auth_client, test_db_session, test_org):
    from sqlalchemy import select

    from aios.governance.security import SecurityEvent

    other = Organization(name="Other", slug="other-model-org")
    test_db_session.add(other)
    await test_db_session.flush()
    secret = ModelRegistryEntry(
        org_id=other.id, model_key="secret-model", provider="x", approved=True
    )
    test_db_session.add(secret)
    await test_db_session.commit()

    keys = {m["model_key"] for m in (await auth_client.get("/api/models")).json()["items"]}
    assert "secret-model" not in keys
    resp = await auth_client.post(f"/api/models/{secret.id}/approve")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "model registry entry not found"

    events = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    matches = [
        e for e in events
        if (e.payload or {}).get("resource_id") == secret.id
        and (e.payload or {}).get("resource") == "model_registry_entry"
    ]
    assert len(matches) == 1
    assert matches[0].payload["requested_org_id"] == test_org.id
    assert matches[0].payload["resource_org_id"] == other.id


async def test_model_registry_global_visible_no_cross_tenant_metric(auth_client, test_db_session, test_org, test_user):
    from sqlalchemy import select

    from aios.governance.security import SecurityEvent

    global_entry = ModelRegistryEntry(
        org_id=None, model_key="global-model", provider="x", approved=True
    )
    test_db_session.add(global_entry)
    await test_db_session.commit()

    resp = await auth_client.post(f"/api/models/{global_entry.id}/approve")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "cannot approve a global registry entry"

    events = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert not any((e.payload or {}).get("resource_id") == global_entry.id for e in events)


async def test_recommend_for_agent_returns_picks_without_mutation(
    monkeypatch, auth_client, test_db_session, test_org
):
    from aios.core.model_select import Pick

    picks = [
        Pick(model="cheap", score=0.9, price_in=1.0, price_out=2.0, context=8000,
             indices={"speed": 1}, reason="cheap"),
        Pick(model="safe", score=0.8, price_in=3.0, price_out=4.0, context=16000,
             indices={"quality": 2}, reason="safe"),
    ]
    seen = {}

    async def fake_recommend(agent_type, limit):
        seen.update(agent_type=agent_type, limit=limit)
        return picks

    monkeypatch.setattr("aios.core.model_select.recommend", fake_recommend)
    before = dict(test_org.extra_data or {})

    resp = await auth_client.post(
        "/api/models/recommend-for-agent",
        json={"agent_type": "sales", "limit": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert seen == {"agent_type": "sales", "limit": 2}
    assert set(body) == {"items", "requires_founder_approval"}
    assert body["requires_founder_approval"] is True
    assert body["items"] == [
        {"model": "cheap", "score": 0.9, "price_in": 1.0, "price_out": 2.0,
         "context": 8000, "indices": {"speed": 1}, "reason": "cheap"},
        {"model": "safe", "score": 0.8, "price_in": 3.0, "price_out": 4.0,
         "context": 16000, "indices": {"quality": 2}, "reason": "safe"},
    ]

    await test_db_session.refresh(test_org)
    assert (test_org.extra_data or {}) == before  # endpoint is read-only
