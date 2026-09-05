from httpx import AsyncClient
from unittest.mock import patch, AsyncMock


class TestPromptLab:
    async def test_promptlab_test(self, auth_client: AsyncClient):
        with patch("aios.core.providers.get_provider") as mock:
            m = AsyncMock()
            m.chat_retry = AsyncMock(return_value={"content": "hello"})
            mock.return_value = m
            r = await auth_client.post("/api/promptlab/test", json={"system_prompt": "You are helpful", "user_input": "hi"})
            assert r.status_code == 200
            assert "output" in r.json()

    async def test_dataset_upload(self, auth_client: AsyncClient):
        c = await auth_client.post("/api/agents", json={"name": "DS Agent"})
        aid = c.json()["id"]
        r = await auth_client.post(f"/api/agents/{aid}/datasets", json={"name": "ds1", "cases": [{"input": "a", "expected": "b"}]})
        assert r.status_code == 200
        lst = await auth_client.get(f"/api/agents/{aid}/datasets")
        assert lst.status_code == 200
