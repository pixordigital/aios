"""Focused regressions for issues found in the VibeSec whole-app pass."""

import subprocess

import pytest


def test_shared_url_guard_rejects_embedded_credentials_and_invalid_port(monkeypatch):
    import aios.tools.ssrf as ssrf

    monkeypatch.setattr(ssrf, "is_private_host", lambda _host: False)
    assert ssrf.check_url("https://user:secret@example.com/") == "URL credentials are not allowed"
    assert ssrf.check_url("https://example.com:99999/") == "invalid URL port"


@pytest.mark.asyncio
async def test_http_request_does_not_forward_request_to_other_origin(monkeypatch):
    import httpx
    import aios.tools.http_request as module

    monkeypatch.setenv("AIOS_ALLOW_PRIVATE_HTTP", "1")
    monkeypatch.setattr(module, "check_url", lambda *_args, **_kwargs: None)
    requests = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, method, url, **kwargs):
            requests.append((method, str(url), kwargs))
            return httpx.Response(302, headers={"location": "https://attacker.example/collect"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await module.HttpRequestTool().run(
        "https://api.example.test/data", auth_type="bearer", auth_value="sensitive-token"
    )

    assert result["error"] == "cross-origin redirects are blocked"
    assert len(requests) == 1
    assert requests[0][2]["headers"]["Authorization"] == "Bearer sensitive-token"


def test_backup_restore_uses_argument_vectors_without_shell(monkeypatch, tmp_path):
    from aios.dashboard.app import _restore_backup_dump

    calls = []

    class FakePipe:
        def close(self):
            pass

    class FakeProcess:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))
            self.args = args
            self.stdout = FakePipe() if kwargs.get("stdout") == subprocess.PIPE else None
            self.returncode = None

        def communicate(self, timeout=None):
            self.returncode = 0
            return b"restored", b""

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    archive = tmp_path / "backup; touch PWNED.sql.gz"
    code, stdout, stderr = _restore_backup_dump(archive, "postgresql+asyncpg://db/test")

    assert code == 0 and stdout == "restored" and stderr == ""
    assert calls[0][0] == ["gzip", "-dc", "--", str(archive)]
    assert calls[1][0] == ["psql", "postgresql://db/test"]
    assert all("shell" not in kwargs or kwargs["shell"] is False for _, kwargs in calls)


@pytest.mark.asyncio
async def test_sql_query_blocks_refresh_tokens_table():
    from aios.tools.sql_query import SQLQueryTool

    tool = SQLQueryTool()
    result = await tool.run("SELECT jti, user_id FROM refresh_tokens")
    assert "error" in result
    assert "refresh_tokens" not in str(result).lower() or "bloqueada" in str(result.get("error", "")).lower()
    assert "bloqueada" in result["error"].lower()
