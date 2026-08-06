"""Tests for the dead-letter queue (retry/DLQ).

Pure-logic for entry mapping; DB+HTTP for write/list/retry/clear
against the test SQLite DB via admin API.
"""

from aios.config import settings
from aios.db.models import _now

ADMIN_KEY = settings.admin_master_key


# ─── Entry mapping ───

def test_entry_to_dict_maps_fields():
    from aios.core.dead_letter import _entry_to_dict

    class Stub:
        id = "e1"
        org_id = "o1"
        channel_type = "whatsapp"
        channel_connection_id = "c1"
        conversation_id = "conv1"
        direction = "outbound"
        job_name = "aios.core.delivery.deliver_message"
        payload = {"args": ["a"]}
        error = "boom"
        attempts = 3
        status = "failed"
        retried_at = None
        created_at = _now()

    d = _entry_to_dict(Stub())
    assert d["id"] == "e1"
    assert d["direction"] == "outbound"
    assert d["job_name"].endswith("deliver_message")
    assert d["payload"] == {"args": ["a"]}
    assert d["retried_at"] is None
    assert "T" in d["created_at"]  # isoformat timestamp


# ─── Admin API (DB-backed) ───

async def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {ADMIN_KEY}"}


async def test_dlq_list_requires_admin_key(async_client):
    r = await async_client.get("/api/admin/dlq")
    assert r.status_code == 403


async def test_dlq_empty(async_client):
    r = await async_client.get("/api/admin/dlq", headers=await _admin_headers())
    assert r.status_code == 200
    assert r.json()["entries"] == []
    assert r.json()["count"] == 0


async def test_dlq_insert_and_list(async_client):
    from aios.core.dead_letter import write_dlq
    await write_dlq(
        direction="outbound",
        channel_type="whatsapp",
        job_name="aios.core.delivery.deliver_message",
        payload={"args": ["ch1", "conv1", "hi", "{}"], "kwargs": {}},
        error="boom",
        channel_connection_id="ch1",
        conversation_id="conv1",
    )
    r = await async_client.get("/api/admin/dlq", headers=await _admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    e = body["entries"][0]
    assert e["channel_type"] == "whatsapp"
    assert e["direction"] == "outbound"
    assert e["error"] == "boom"
    assert e["payload"]["args"][0] == "ch1"


async def test_dlq_retry_missing_returns_404(async_client):
    r = await async_client.post("/api/admin/dlq/nope/retry", headers=await _admin_headers())
    assert r.status_code == 404


async def test_dlq_retry_sets_status(async_client):
    from aios.core.dead_letter import write_dlq
    import aios.tasks.queue as queue_mod
    from aios.db.models import DeadLetter
    from sqlalchemy import select

    eid = await write_dlq(
        direction="inbound",
        channel_type="whatsapp",
        job_name="aios.tasks.jobs.process_inbound",
        payload={"args": ["whatsapp", "ch1", "conv1", "hi", "", "{}"], "kwargs": {}},
        error="fail",
        channel_connection_id="ch1",
    )

    class FakePool:
        def __init__(self):
            self.enqueued = None

        async def enqueue_job(self, *a, **k):
            self.enqueued = (a, k)

    fake = FakePool()
    orig = queue_mod.get_redis_pool

    async def _fake_pool():
        return fake

    # retry_dlq does `from aios.tasks.queue import get_redis_pool` inside —
    # patch the queue module so it returns the fake pool.
    queue_mod.get_redis_pool = _fake_pool
    try:
        from aios.core.dead_letter import retry_dlq
        r = await retry_dlq(eid)
        assert r["ok"] is True
        assert fake.enqueued is not None
        assert fake.enqueued[0][0] == "aios.tasks.jobs.process_inbound"
    finally:
        queue_mod.get_redis_pool = orig

    # entry marked retried with timestamp
    from aios.db.backend import db_session
    async with db_session() as db:
        entry = await db.get(DeadLetter, eid)
        assert entry.status == "retried"
        assert entry.retried_at is not None


async def test_dlq_clear(async_client):
    from aios.core.dead_letter import write_dlq
    await write_dlq(direction="outbound", channel_type="x", job_name="j", payload={}, error="e1")
    await write_dlq(direction="inbound", channel_type="x", job_name="j", payload={}, error="e2")
    r = await async_client.post("/api/admin/dlq/clear", headers=await _admin_headers())
    assert r.status_code == 200
    assert r.json()["cleared"] == 2
    r = await async_client.get("/api/admin/dlq", headers=await _admin_headers())
    assert r.json()["count"] == 0
