"""Dashboard designer: design-only and design+local-install wiring."""
import jwt
import pytest
from datetime import datetime, timedelta, timezone

from aios.config import settings


def _cookie(user):
    return jwt.encode(
        {
            "sub": user.id,
            "org": user.org_id,
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_design_page_wires_design_and_install(async_client, test_user, tmp_path):
    async_client.cookies.set("aios_token", _cookie(test_user))
    headers = {"referer": "http://test/dashboard/agent-packs/design"}
    data = {
        "base_key": "vender",
        "vertical": "clinica de estetica",
        "addon": "Voce e o time comercial da clinica.",
        "runtime_target": "openbot",
    }

    r = await async_client.post("/dashboard/agent-packs/design", data=data, headers=headers)
    assert r.status_code == 200, r.text
    assert "sol-vender-clinica-de-estetica" in r.text, r.text[r.text.find("Erro:"):r.text.find("Erro:") + 400]
    assert ">openbot</span>" in r.text

    target_root = tmp_path / "openbot"
    r = await async_client.post(
        "/dashboard/agent-packs/design",
        data={
            **data,
            "action": "install",
            "consent_phrase": "UNSIGNED_RISK_ACCEPTED install into test dir",
            "allow_unsigned": "true",
            "accept_capability_loss": "true",
            "target_root": str(target_root),
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "install:</span> ok" in r.text, r.text[r.text.find("Erro:"):r.text.find("Erro:") + 500]
    assert (target_root / "openbot" / "agent.bundle.json").is_file()
