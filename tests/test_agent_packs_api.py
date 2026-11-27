import copy

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from aios.api.auth import _hash_password
from aios.core.agent_pack import _checksum_fingerprint, manifest_fingerprint, validate_agent_pack
from aios.db.models import AgentPack, AgentPackActivation, Organization, PendingAction, User
from aios.main import app


def _manifest(pack_key="sales-sdr", version="1.0.0"):
    data = {
        "schema_version": "1.0.0",
        "version": version,
        "identity": {
            "id": pack_key,
            "name": "Sales SDR",
            "agent_type": "sdr",
            "description": "desc",
            "owner": "team",
            "tags": ["sales"],
        },
        "prompt": {"system_prompt": "You are an SDR.", "variables": ["company"], "scaffold_required": True},
        "tools": {"allowed_tools": ["crm_lookup"], "denied_tools": ["delete_db"], "risk_classes": {"crm_lookup": "read"}},
        "routines": [{"id": "qualify", "trigger": "new_lead", "workflow_id": "wf1", "stage_ref": "stages/qualify.v1", "enabled": True}],
        "approvals": {"mode": "ask_tools", "required_for": ["send_email"], "approval_ttl_seconds": 300, "explicit_preapproved_allowed": False},
        "memory_scope": {"scopes": ["conversation", "agent"], "max_short_term_messages": 100, "long_term_enabled": True, "episodic_enabled": True, "redact_patterns": []},
        "runtime_targets": [{"target": "local_proc", "entrypoint": "main:run", "image": None, "resources": {}}],
        "changelog": [{"version": version, "date": "2026-11-25", "summary": "init", "author": "pixor"}],
        "provenance": {"source": "git:test", "created_by": "tester", "created_at": "2026-11-25T00:00:00Z", "checksum_sha256": None, "signature": None, "parent_fingerprint": None},
    }
    m = validate_agent_pack(copy.deepcopy(data))
    data["provenance"]["checksum_sha256"] = _checksum_fingerprint(m)
    # sanity
    validate_agent_pack(copy.deepcopy(data))
    return data


async def _auth_client_for_user(user, org):
    import jwt
    from datetime import datetime, timedelta, timezone

    token = jwt.encode(
        {"sub": user.id, "org": org.id, "type": "access", "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=60)},
        "test-secret",
        algorithm="HS256",
    )
    transport = ASGITransport(app=app)
    c = AsyncClient(transport=transport, base_url="http://test")
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


@pytest.mark.asyncio
async def test_install_valid_manifest(test_db_session, auth_client):
    body = {"manifest": _manifest(), "capability_loss": [], "accept_high_severity_loss": False}
    r = await auth_client.post("/api/agent-packs/install", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["pack"]["pack_key"] == "sales-sdr"
    assert data["version"]["version_semver"] == "1.0.0"
    assert data["version"]["checksum_sha256"]


@pytest.mark.asyncio
async def test_install_rejects_invalid_extra_checksum_and_high_loss(test_db_session, auth_client):
    bad_extra = _manifest()
    bad_extra["unknown"] = "x"
    r = await auth_client.post("/api/agent-packs/install", json={"manifest": bad_extra})
    assert r.status_code == 422

    bad_checksum = _manifest()
    bad_checksum["provenance"]["checksum_sha256"] = "0" * 64
    r = await auth_client.post("/api/agent-packs/install", json={"manifest": bad_checksum})
    assert r.status_code == 422

    high_loss = {"manifest": _manifest(pack_key="high-loss"), "capability_loss": [{"id": "x", "severity": "high", "reason_code": "binding_external", "source_path": "p", "source_field": "f", "detail": "d"}], "accept_high_severity_loss": False}
    r = await auth_client.post("/api/agent-packs/install", json=high_loss)
    assert r.status_code == 422
    high_loss["accept_high_severity_loss"] = True
    r = await auth_client.post("/api/agent-packs/install", json=high_loss)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_activate_creates_pending_action_and_does_not_activate(test_db_session, auth_client):
    m = _manifest(pack_key="activate-me")
    r = await auth_client.post("/api/agent-packs/install", json={"manifest": m})
    assert r.status_code == 200
    pack = r.json()["pack"]
    version = r.json()["version"]

    r = await auth_client.post(f"/api/agent-packs/{pack['id']}/activate", json={"version_id": version["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval_action"]["status"] == "pending"
    assert body["activation"]["status"] == "requested"

    # pack not active
    r = await auth_client.get(f"/api/agent-packs/{pack['id']}")
    assert r.status_code == 200
    assert r.json()["pack"]["active_version_id"] is None

    # pending action exists in DB
    pa = await test_db_session.get(PendingAction, body["approval_action"]["id"])
    assert pa is not None
    assert pa.tool_name == "agent_pack_activate"
    assert pa.status == "pending"
    assert pa.tool_args["explicit_preapproved_allowed"] is False


@pytest.mark.asyncio
async def test_design_agent_pack_from_base_solution(test_db_session, auth_client):
    r = await auth_client.post(
        "/api/agent-packs/design",
        json={"base_key": "vender", "vertical": "clinica de estetica", "addon": "Voce e o time comercial da clinica."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_key"] == "vender"
    assert body["manifest"]["version"] == "1.0.0"
    assert body["manifest"]["identity"]["id"].startswith("sol-vender-")

    r = await auth_client.post("/api/agent-packs/design", json={"base_key": "nope", "vertical": "x", "addon": "y"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_approve_applies_activation_idempotent(test_db_session, auth_client, test_org, test_user):
    # create second admin user as approver (self-approval forbidden)
    approver = User(email="approver@example.com", hashed_password=_hash_password("testpass123"), org_id=test_org.id, role="admin")
    test_db_session.add(approver)
    await test_db_session.commit()
    await test_db_session.refresh(approver)
    approver_client = await _auth_client_for_user(approver, test_org)

    m = _manifest(pack_key="approve-me")
    r = await auth_client.post("/api/agent-packs/install", json={"manifest": m})
    pack = r.json()["pack"]
    version = r.json()["version"]
    r = await auth_client.post(f"/api/agent-packs/{pack['id']}/activate", json={"version_id": version["id"]})
    action_id = r.json()["approval_action"]["id"]
    activation_id = r.json()["activation"]["id"]

    r = await approver_client.post(f"/api/approvals/{action_id}/approve")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body.get("apply", {}).get("ok") is True

    pack_row = await test_db_session.get(AgentPack, pack["id"])
    assert pack_row.active_version_id == version["id"]
    act = await test_db_session.get(AgentPackActivation, activation_id)
    assert act.status == "active"

    # idempotent apply via endpoint
    r = await approver_client.post(f"/api/agent-packs/activations/{activation_id}/apply")
    assert r.status_code == 200, r.text
    assert r.json()["idempotent"] is True

    # DB CAS: still one active activation
    acts = (await test_db_session.execute(select(AgentPackActivation).where(AgentPackActivation.pack_id == pack["id"]))).scalars().all()
    assert sum(1 for a in acts if a.status == "active") == 1

    await approver_client.aclose()


@pytest.mark.asyncio
async def test_cross_org_404(test_db_session, auth_client, test_org):
    org2 = Organization(name="Org2", slug="org2-pack", extra_data={"plan": "pro"})
    test_db_session.add(org2)
    await test_db_session.commit()
    await test_db_session.refresh(org2)
    user2 = User(email="u2@example.com", hashed_password=_hash_password("testpass123"), org_id=org2.id, role="admin")
    test_db_session.add(user2)
    await test_db_session.commit()
    await test_db_session.refresh(user2)
    client2 = await _auth_client_for_user(user2, org2)

    r = await auth_client.post("/api/agent-packs/install", json={"manifest": _manifest(pack_key="cross-org")})
    pack_id = r.json()["pack"]["id"]

    r = await client2.get(f"/api/agent-packs/{pack_id}")
    assert r.status_code == 404

    await client2.aclose()


@pytest.mark.asyncio
async def test_no_external_install_calls(test_db_session, auth_client, monkeypatch):
    import subprocess, socket, httpx

    def boom(*args, **kwargs):
        raise AssertionError("external install/network call forbidden")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(socket, "create_connection", boom)

    orig_request = httpx.AsyncClient.request

    async def guarded_request(self, method, url, *args, **kwargs):
        u = str(url)
        if u.startswith("http") and not u.startswith("http://test"):
            raise AssertionError(f"external http forbidden: {u}")
        return await orig_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", guarded_request)

    r = await auth_client.post("/api/agent-packs/install", json={"manifest": _manifest(pack_key="no-ext")})
    assert r.status_code == 200
