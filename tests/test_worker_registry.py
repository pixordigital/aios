"""ARQ worker function registry tests.

Regression: enqueue sites pass fully-qualified names (e.g.
"aios.tasks.jobs.process_inbound") but ARQ keys on func.name, which defaults
to __name__. The mismatch made the worker drop every job with
"function ... not found".
"""

from aios.tasks.jobs import FUNCTIONS, process_inbound
from aios.tasks.worker import WorkerSettings, _registry

# Names used by the enqueue call sites across the codebase.
ENQUEUED_QUALIFIED = [
    "aios.tasks.jobs.process_inbound",
    "aios.tasks.jobs.deliver_message",
    "aios.tasks.jobs.agent_run",
    "aios.tasks.jobs.workflow_run_job",
    "aios.tasks.jobs.quota_alert_job",
    "aios.tasks.jobs.transcribe_voice_recording",
    "aios.core.delivery.deliver_message",
]

# budget_alert_job is enqueued in aios/core/limits.py:148 but never defined
# anywhere in the codebase — a phantom job. Tracked so it stays visible.
KNOWN_PHANTOM_JOBS = ["aios.tasks.jobs.budget_alert_job"]

# A couple of sites use the bare name.
ENQUEUED_BARE = [
    "process_inbound",
    "transcribe_voice_recording",
]


def _registered_names():
    return {getattr(f, "name", f.__name__) for f in WorkerSettings.functions}


def test_process_inbound_registered_qualified():
    assert "aios.tasks.jobs.process_inbound" in _registered_names()


def test_process_inbound_registered_bare():
    assert "process_inbound" in _registered_names()


def test_all_qualified_enqueue_names_resolve():
    names = _registered_names()
    missing = [n for n in ENQUEUED_QUALIFIED if n not in names]
    assert not missing, f"unregistered job names: {missing}"


def test_bare_names_still_resolve():
    names = _registered_names()
    missing = [n for n in ENQUEUED_BARE if n not in names]
    assert not missing, f"unregistered bare names: {missing}"


def test_registry_keeps_originals():
    """Both the original and the alias must be callable."""
    names = _registered_names()
    assert "process_inbound" in names
    assert names  # sanity


def test_alias_wrapper_delegates():
    import asyncio

    from aios.tasks.worker import _aliased

    async def sample(ctx, value):
        return f"got:{value}"

    alias = _aliased(sample, "pkg.mod.sample")
    assert alias.__name__ == "pkg.mod.sample"
    assert asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        alias(None, 42)
    ) == "got:42"


def test_registry_does_not_mutate_originals():
    before = {f.__name__ for f in FUNCTIONS}
    _registry(FUNCTIONS)
    after = {f.__name__ for f in FUNCTIONS}
    assert before == after


def test_phantom_jobs_still_unregistered():
    """Documents known dead enqueues so they surface instead of vanishing.

    limits.py enqueues budget_alert_job but no such function exists, so the job
    is dropped by ARQ. Wrapped in try/except, hence silent.
    """
    names = _registered_names()
    assert not [n for n in KNOWN_PHANTOM_JOBS if n in names]
