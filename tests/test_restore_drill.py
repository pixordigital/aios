"""Smoke for deploy/restore_drill.sh — safe, temp-only, no prod data."""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "restore_drill.sh"


def _run(args: list[str], env: dict[str, str], cwd: Path | None = None):
    return subprocess.run(
        args,
        cwd=str(cwd or ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("AIOS_DATABASE_URL", None)
    env.pop("DATABASE_URL", None)
    env["TMPDIR"] = str(tmp_path)
    return env


def _make_sqlite_backup(tmp_path: Path) -> Path:
    db = tmp_path / "src.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE organizations(id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE users(id TEXT PRIMARY KEY, email TEXT)")
    conn.execute("CREATE TABLE agents(id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO organizations(id,name) VALUES ('o1','Org')")
    conn.execute("INSERT INTO users(id,email) VALUES ('u1','u@example.com')")
    conn.execute("INSERT INTO agents(id,name) VALUES ('a1','Agent')")
    conn.commit()
    conn.close()
    backup = tmp_path / "aios_20260101_000000.sqlite.gz"
    with open(db, "rb") as src, gzip.open(backup, "wb") as dst:
        dst.write(src.read())
    return backup


@pytest.mark.skipif(not SCRIPT.exists(), reason="restore drill script missing")
def test_restore_drill_sqlite_temp_backup_emits_report(tmp_path: Path):
    backup = _make_sqlite_backup(tmp_path)
    report = tmp_path / "evidence.json"
    env = _base_env(tmp_path)
    env["AIOS_RESTORE_DRILL_TARGET_URL"] = f"sqlite:///{tmp_path / 'restore_drill_target.db'}"
    env["AIOS_RESTORE_DRILL_CONFIRM"] = "I_UNDERSTAND_THIS_IS_ISOLATED"

    r = _run(["bash", str(SCRIPT), str(backup), "--report", str(report)], env)

    assert r.returncode == 0, r.stderr + "\n" + r.stdout
    assert report.exists()
    data = json.loads(report.read_text())
    assert data["status"] == "passed"
    assert data["backup_sha256"]
    checks = {c["name"]: c for c in data["checks"]}
    assert checks["sqlite_integrity_check"]["ok"] is True
    assert checks["sqlite_foreign_key_check"]["ok"] is True
    assert checks["sqlite_tables_present"]["ok"] is True


@pytest.mark.skipif(not SCRIPT.exists(), reason="restore drill script missing")
def test_restore_drill_fails_closed_on_prod_like_target(tmp_path: Path):
    backup = _make_sqlite_backup(tmp_path)
    report = tmp_path / "evidence.json"
    env = _base_env(tmp_path)
    env["AIOS_RESTORE_DRILL_TARGET_URL"] = "postgresql://user:pass@prod-db:5432/aios_production"
    env["AIOS_RESTORE_DRILL_CONFIRM"] = "I_UNDERSTAND_THIS_IS_ISOLATED"

    r = _run(["bash", str(SCRIPT), str(backup), "--report", str(report)], env)

    assert r.returncode != 0
    assert "refusing" in r.stderr.lower() or "unsafe" in r.stderr.lower()
    assert not report.exists() or json.loads(report.read_text()).get("status") != "passed"


@pytest.mark.skipif(not SCRIPT.exists(), reason="restore drill script missing")
def test_restore_drill_requires_confirmation(tmp_path: Path):
    backup = _make_sqlite_backup(tmp_path)
    env = _base_env(tmp_path)
    env["AIOS_RESTORE_DRILL_TARGET_URL"] = f"sqlite:///{tmp_path / 'restore_drill_target.db'}"
    env.pop("AIOS_RESTORE_DRILL_CONFIRM", None)

    r = _run(["bash", str(SCRIPT), str(backup)], env)

    assert r.returncode != 0
    assert "confirm" in r.stderr.lower()
