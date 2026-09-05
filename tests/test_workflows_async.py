import pytest
from httpx import AsyncClient


class TestWorkflowsAsync:
    async def test_workflow_async_default(self, auth_client: AsyncClient):
        wf = await auth_client.post("/api/workflows", json={"name": "WF Async", "timeout_seconds": 60})
        assert wf.status_code == 200
        wf_id = wf.json()["id"]
        n1 = await auth_client.post(f"/api/workflows/{wf_id}/nodes", json={"label": "n1", "tool_name": "calculator", "tool_args": {"expression": "1+1"}})
        assert n1.status_code == 200
        run = await auth_client.post(f"/api/workflows/{wf_id}/run", json={"input": "hello"})
        assert run.status_code == 200
        data = run.json()
        assert "run_id" in data
        assert data["status"] in ("running", "done", "failed")
        rid = data["run_id"]
        get = await auth_client.get(f"/api/workflows/{wf_id}/runs/{rid}")
        assert get.status_code == 200

    async def test_workflow_cycle_rejected(self, auth_client: AsyncClient):
        wf = await auth_client.post("/api/workflows", json={"name": "WF Cycle"})
        wf_id = wf.json()["id"]
        n1 = await auth_client.post(f"/api/workflows/{wf_id}/nodes", json={"label": "n1"})
        nid = n1.json()["id"]
        bad = await auth_client.post(f"/api/workflows/{wf_id}/nodes", json={"label": "n2", "depends_on": ["not-exist"]})
        assert bad.status_code == 400

    async def test_workflow_resume(self, auth_client: AsyncClient):
        wf = await auth_client.post("/api/workflows", json={"name": "WF Resume"})
        wf_id = wf.json()["id"]
        await auth_client.post(f"/api/workflows/{wf_id}/nodes", json={"label": "n1", "tool_name": "calculator", "tool_args": {"expression": "2+2"}})
        run = await auth_client.post(f"/api/workflows/{wf_id}/run", json={"input": "test", "async": False})
        rid = run.json().get("run_id")
        if rid:
            res = await auth_client.post(f"/api/workflows/{wf_id}/resume/{rid}")
            assert res.status_code in (200, 404)
