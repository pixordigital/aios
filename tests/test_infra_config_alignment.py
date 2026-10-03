"""Infra regressions: config drift between the code and the compose files.

These are cheap source-level assertions on purpose. Booting four compose
files per commit is not viable in CI, but every one of these defects shipped
because nothing compared what the code reads against what compose passes.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE_FILES = [
    "docker-compose.coolify.yml",
    "docker-compose.coolify.one-click.yml",
]


@pytest.mark.parametrize("path", COMPOSE_FILES)
def test_evolution_env_vars_carry_the_settings_prefix(path):
    """Settings uses env_prefix="AIOS_". An unprefixed EVOLUTION_API_KEY was
    read as an unrelated var, so settings.evolution_api_key stayed "" and every
    inbound message came back "unknown_instance"."""
    text = (ROOT / path).read_text()
    # Evolution's own container reads plain EVOLUTION_* and SERVER_URL; only the
    # app/worker services go through Settings, which is where the prefix matters.
    unprefixed = re.findall(
        r"^\s+(?<!AUTHENTICATION_)EVOLUTION_(?:API_KEY|SERVER_URL):", text, re.M
    )
    assert not unprefixed, (
        f"{path}: {unprefixed} lack the AIOS_ prefix — the app process will not read them"
    )
    assert "AIOS_EVOLUTION_API_KEY" in text, f"{path}: AIOS_EVOLUTION_API_KEY missing"


@pytest.mark.parametrize("path", COMPOSE_FILES)
def test_pg_host_matches_a_declared_service(path):
    """app and worker pointed at `supabase-db` while the file declares a
    service named `postgres`: pg_isready never succeeded and every DB access
    failed, so every inbound message dead-lettered."""
    text = (ROOT / path).read_text()
    services = set(re.findall(r"^  ([a-z0-9_-]+):\s*$", text, re.M))
    for host in set(re.findall(r"@(?:PGHOST: )?([a-z0-9_-]+):5432", text)):
        assert host in services, (
            f"{path}: points at host '{host}' which is not a service in this file "
            f"(declared: {sorted(services)})"
        )


def test_worker_and_api_share_one_redis_parser():
    """worker.py had its own copy of the Redis URL parser, missing `username`,
    `ssl` and the REDIS_HOST fallback — so the worker could fail to authenticate
    (or dialled localhost) while the API worked fine."""
    worker = (ROOT / "aios/tasks/worker.py").read_text()
    assert "from .queue import _parse_redis as _shared" in worker, (
        "worker.py re-implements the Redis URL parser instead of reusing queue.py"
    )


def test_worker_redis_url_does_not_default_to_localhost():
    """settings.redis_url unset + REDIS_HOST=redis (compose) must not resolve to
    localhost: the worker then polls a Redis that does not exist and never
    picks up a job."""
    worker = (ROOT / "aios/tasks/worker.py").read_text()
    assert '"redis://localhost:6379"' not in worker, (
        "worker still falls back to a hardcoded localhost Redis"
    )


def test_no_committed_database_superuser():
    """A Supabase superuser password was committed in docker-compose.yaml.
    `supabase_admin` is not a tenant role — it is full control of the database
    behind every tenant."""
    for path in ROOT.glob("docker-compose*.y*ml"):
        text = path.read_text()
        assert "supabase_admin" not in text, (
            f"{path.name} still carries the Supabase superuser credential"
        )


def test_app_data_dir_points_at_the_mounted_volume():
    """compose mounts the volume at /data but app_data_dir defaulted to
    "./data" (= /app/data), so artifacts, per-agent vector memory and tracing
    metrics lived on the container overlay and died on every redeploy."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "AIOS_APP_DATA_DIR=/data" in dockerfile, (
        "Dockerfile must set AIOS_APP_DATA_DIR=/data to match the mounted volume"
    )


def test_failed_migration_is_not_silently_stamped():
    """`alembic stamp head` after a genuine failure marks pending revisions
    applied without running them; create_all never ALTERs, so the release ships
    missing columns behind a 200 from /health/ready."""
    entry = (ROOT / "deploy/entrypoint.sh").read_text()
    assert "_has_version" in entry, "entrypoint must distinguish a stamped DB before stamping"
    assert "Refusing to stamp head" in entry


def test_ci_smoke_test_targets_the_deployed_compose():
    """Bare `docker compose up` resolved to docker-compose.yml (the dev stack),
    so the Coolify compose that actually ships was never exercised."""
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "-f docker-compose.coolify.yml" in ci, (
        "CI must pin the compose file it actually deploys"
    )
    assert re.search(r"^\s*- run: docker compose up -d", ci, re.M) is None, (
        "CI still uses an unpinned `docker compose up -d`"
    )


def test_worker_health_is_verified_in_ci():
    """Agent runs happen in the worker. An app-only smoke test passed while the
    worker crash-looped."""
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "ps -q worker" in ci, "CI must check the worker container is running"