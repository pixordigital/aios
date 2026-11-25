"""Cross-tenant telemetry coverage for meta and agent-pack producers."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from aios.api.agent_packs import _request_activation, apply_agent_pack_activation
from aios.api.auth import _hash_password
from aios.db.models import Agent, AgentPack, AgentPackActivation, AgentPackVersion, PendingAction, User
from aios.governance.security import SecurityEvent
from tests.test_agent_packs_api import _auth_client_for_user, _manifest

EVENT_TYPE = "security.cross_tenant.blocked"


async def _events(db):
    rows = (
        await db.execute(select(SecurityEvent).where(SecurityEvent.event_type == EVENT_TYPE))
    ).scalars().all()
    return list(rows)


def _assert_event(event, *, org_id, actor_id, source, resource_type, resource_org_id, payload):
    assert event.event_type == EVENT_TYPE
    assert event.org_id == org_id
    assert event.actor_type == "human"
    assert event.actor_id == actor_id
    assert event.source == source
    assert event.payload == {
        **payload,
        "metric": "cross_tenant_block",
        "requested_org_id": org_id,
        "resource_org_id": resource_org_id,
        "resource_type": resource_type,
    }


async def _pack_version(db, *, org_id, pack_key):
    pack = AgentPack(org_id=org_id, pack_key=pack_key, name="Pack")
    db.add(pack)
    await db.flush()
    version = AgentPackVersion(
        pack_id=pack.id,
        org_id=org_id,
        version_semver="1.0.0",
        checksum_sha256="c",
        fingerprint_sha256="f",
    )
    db.add(version)
    await db.commit()
    await db.refresh(pack)
    await db.refresh(version)
    return pack, version


async def _approved_pack_action(test_db_session, auth_client, test_org, test_user, monkeypatch, pack_key):
    """Real approval flow; only the post-approval apply side effect is stubbed."""
    from aios.api import agent_packs

    async def _no_apply(db, action):
        return {"ok": True, "idempotent": False, "activation_id": None, "status": "active"}

    monkeypatch.setattr(agent_packs, "apply_agent_pack_activation", _no_apply)

    approver = User(
        email=f"{pack_key}@example.com",
        hashed_password=_hash_password("testpass123"),
        org_id=test_org.id,
        role="admin",
    )
    test_db_session.add(approver)
    await test_db_session.commit()
    await test_db_session.refresh(approver)
    approver_client = await _auth_client_for_user(approver, test_org)

    installed = await auth_client.post("/api/agent-packs/install", json={"manifest": _manifest(pack_key=pack_key)})
    assert installed.status_code == 200, installed.text
    pack = installed.json()["pack"]
    version = installed.json()["version"]
    requested = await auth_client.post(
        f"/api/agent-packs/{pack['id']}/activate", json={"version_id": version["id"]}
    )
    assert requested.status_code == 200, requested.text
    action_id = requested.json()["approval_action"]["id"]
    activation_id = requested.json()["activation"]["id"]

    approved = await approver_client.post(f"/api/approvals/{action_id}/approve")
    assert approved.status_code == 200, approved.text
    await approver_client.aclose()

    action = (
        await test_db_session.execute(
            select(PendingAction)
            .where(PendingAction.id == action_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert action.status == "approved"
    activation = await test_db_session.get(AgentPackActivation, activation_id)
    return action, activation, approver


@pytest.mark.asyncio(loop_scope="function")
async def test_meta_apply_keeps_404_and_emits_only_for_foreign_agent(
    auth_client, test_db_session, test_user, second_org
):
    foreign = Agent(org_id=second_org.id, name="Foreign", system_prompt="secret prompt")
    test_db_session.add(foreign)
    await test_db_session.commit()
    await test_db_session.refresh(foreign)

    suggestion = "never echo this suggestion"
    resp = await auth_client.post(
        "/api/meta/apply", json={"agent_id": foreign.id, "suggestion": suggestion}
    )
    assert resp.status_code == 404, resp.text

    rows = await _events(test_db_session)
    assert len(rows) == 1
    _assert_event(
        rows[0],
        org_id=test_user.org_id,
        actor_id=test_user.id,
        source="api.meta.apply_improvement",
        resource_type="Agent",
        resource_org_id=second_org.id,
        payload={"agent_id": foreign.id},
    )
    assert suggestion not in str(rows[0].payload)

    own = Agent(org_id=test_user.org_id, name="Own", system_prompt="own")
    test_db_session.add(own)
    await test_db_session.commit()
    await test_db_session.refresh(own)
    assert (await auth_client.post(
        "/api/meta/apply", json={"agent_id": own.id, "suggestion": "benign"}
    )).status_code == 200
    assert (await auth_client.post(
        "/api/meta/apply", json={"agent_id": "missing-agent", "suggestion": "benign"}
    )).status_code == 404
    assert len(await _events(test_db_session)) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_request_activation_keeps_404_and_emits_only_for_foreign_pack(
    test_db_session, test_user, second_org
):
    foreign_pack, foreign_version = await _pack_version(
        test_db_session, org_id=second_org.id, pack_key="cross-request"
    )
    with pytest.raises(HTTPException) as exc:
        await _request_activation(
            test_db_session,
            org_id=test_user.org_id,
            user_id=test_user.id,
            pack=foreign_pack,
            version=foreign_version,
            action_type="activate",
        )
    assert exc.value.status_code == 404

    rows = await _events(test_db_session)
    assert len(rows) == 1
    _assert_event(
        rows[0],
        org_id=test_user.org_id,
        actor_id=test_user.id,
        source="agent_packs.api.request_activation",
        resource_type="AgentPackVersion",
        resource_org_id=second_org.id,
        payload={"pack_id": foreign_pack.id, "version_id": foreign_version.id},
    )

    own_pack, own_version = await _pack_version(
        test_db_session, org_id=test_user.org_id, pack_key="own-request"
    )
    result = await _request_activation(
        test_db_session,
        org_id=test_user.org_id,
        user_id=test_user.id,
        pack=own_pack,
        version=own_version,
        action_type="activate",
    )
    assert result["approval_action"]["status"] == "pending"
    assert len(await _events(test_db_session)) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_apply_activation_activation_org_mismatch_keeps_ok_false(
    test_db_session, auth_client, test_org, test_user, monkeypatch, second_org
):
    action, activation, approver = await _approved_pack_action(
        test_db_session, auth_client, test_org, test_user, monkeypatch, "action-org"
    )
    activation.org_id = second_org.id
    await test_db_session.commit()

    result = await apply_agent_pack_activation(test_db_session, action)
    assert result == {"ok": False, "reason": "org_mismatch", "activation_id": activation.id}

    rows = await _events(test_db_session)
    assert len(rows) == 1
    _assert_event(
        rows[0],
        org_id=test_org.id,
        actor_id=approver.id,
        source="agent_packs.api.apply_activation.activation",
        resource_type="AgentPackActivation",
        resource_org_id=second_org.id,
        payload={"activation_id": activation.id, "approval_action_id": action.id},
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_apply_activation_pack_org_mismatch_keeps_ok_false(
    test_db_session, auth_client, test_org, test_user, monkeypatch, second_org
):
    action, activation, approver = await _approved_pack_action(
        test_db_session, auth_client, test_org, test_user, monkeypatch, "pack-org"
    )
    pack = await test_db_session.get(AgentPack, activation.pack_id)
    pack.org_id = second_org.id
    await test_db_session.commit()

    result = await apply_agent_pack_activation(test_db_session, action)
    assert result == {
        "ok": False,
        "reason": "org_or_pack_mismatch",
        "activation_id": activation.id,
    }

    rows = await _events(test_db_session)
    assert len(rows) == 1
    _assert_event(
        rows[0],
        org_id=test_org.id,
        actor_id=approver.id,
        source="agent_packs.api.apply_activation.pack",
        resource_type="AgentPack",
        resource_org_id=second_org.id,
        payload={
            "activation_id": activation.id,
            "pack_id": pack.id,
            "version_id": activation.version_id,
            "approval_action_id": action.id,
        },
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_missing_activation_stays_silent(
    test_db_session, auth_client, test_org, test_user, monkeypatch
):
    action, activation, _ = await _approved_pack_action(
        test_db_session, auth_client, test_org, test_user, monkeypatch, "missing-activation"
    )
    await test_db_session.delete(activation)
    await test_db_session.commit()

    result = await apply_agent_pack_activation(test_db_session, action)
    assert result == {"ok": False, "reason": "activation_not_found", "activation_id": None}
    assert not await _events(test_db_session)
