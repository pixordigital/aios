"""Cron moved from the API lifespan to the ARQ worker."""

import pytest

from aios.tasks.worker import WorkerSettings, cron_tick_job


def test_cron_tick_registered_and_scheduled():
    names = {getattr(f, "name", f.__name__) for f in WorkerSettings.functions}
    assert "cron_tick_job" in names
    assert "telemetry_flush_job" in names
    assert any(job.name.endswith("cron_tick_job") for job in WorkerSettings.cron_jobs)
    assert any(job.name.endswith("telemetry_flush_job") for job in WorkerSettings.cron_jobs)


@pytest.mark.asyncio
async def test_run_once_on_sqlite(monkeypatch):
    from aios.core.cron_scheduler import run_once

    monkeypatch.setenv("AIOS_BACKUP_ENABLED", "0")
    await run_once()
    await cron_tick_job(None)
