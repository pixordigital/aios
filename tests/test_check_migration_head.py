"""Preflight CLI tests: fake script dirs + temp SQLite; no live DB or LLM creds."""

import ast
import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_migration_head.py"

_spec = importlib.util.spec_from_file_location("check_migration_head", SCRIPT)
checker = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = checker  # dataclass needs the module registered
_spec.loader.exec_module(checker)

# prod -> c9d0 -> d0e1; Supabase (e7f8) sits on the same chain, behind prod.
CHAIN = [
    ("8c9907080a72", None),
    ("e7f8a9b0c1d2", "8c9907080a72"),
    ("b8c9d0e1f2a3", "e7f8a9b0c1d2"),
    ("c9d0e1f2a3b4", "b8c9d0e1f2a3"),
    ("d0e1f2a3b4c5", "c9d0e1f2a3b4"),
]


def _script_dir(tmp_path, pairs):
    directory = tmp_path / "versions"
    directory.mkdir()
    for revision, down in pairs:
        (directory / f"{revision}.py").write_text(
            f'revision = "{revision}"\ndown_revision = {down!r}\n'
        )
    return directory


def _db(tmp_path, *versions):
    path = tmp_path / "alembic.sqlite"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.executemany("INSERT INTO alembic_version VALUES (?)", [(v,) for v in versions])
        conn.commit()
    finally:
        conn.close()
    return f"sqlite+aiosqlite:///{path}"


def test_current_head_passes(tmp_path, capsys):
    scripts = _script_dir(tmp_path, CHAIN)
    dsn = _db(tmp_path, "d0e1f2a3b4c5")

    assert checker.check(["--dsn", dsn, "--script-dir", str(scripts)]) == 0
    out = capsys.readouterr()
    assert "DB head: d0e1f2a3b4c5" in out.out
    assert "Script head: d0e1f2a3b4c5" in out.out
    assert "OK: database head matches" in out.out


def test_behind_uses_env_dsn_and_lists_pending(tmp_path, capsys, monkeypatch):
    scripts = _script_dir(tmp_path, CHAIN)
    monkeypatch.setenv("AIOS_DATABASE_URL", _db(tmp_path, "b8c9d0e1f2a3"))

    assert checker.check(["--script-dir", str(scripts)]) == 1
    out = capsys.readouterr()
    assert "DB head: b8c9d0e1f2a3" in out.out
    assert "Script head: d0e1f2a3b4c5" in out.out
    assert "c9d0e1f2a3b4  c9d0e1f2a3b4.py" in out.out
    assert "d0e1f2a3b4c5  d0e1f2a3b4c5.py" in out.out
    assert "database behind script head" in out.err


def test_supabase_head_is_reported_behind_not_at_target(tmp_path, capsys):
    scripts = _script_dir(tmp_path, CHAIN)
    dsn = _db(tmp_path, "e7f8a9b0c1d2")

    assert checker.check(["--dsn", dsn, "--script-dir", str(scripts)]) == 1
    out = capsys.readouterr()
    assert "DB head: e7f8a9b0c1d2" in out.out
    for revision in ("b8c9d0e1f2a3", "c9d0e1f2a3b4", "d0e1f2a3b4c5"):
        assert revision in out.out


def test_multiple_script_heads_refused(tmp_path, capsys):
    scripts = _script_dir(tmp_path, CHAIN + [("fff000000001", "c9d0e1f2a3b4")])
    dsn = _db(tmp_path, "d0e1f2a3b4c5")

    assert checker.check(["--dsn", dsn, "--script-dir", str(scripts)]) == 1
    assert "multiple heads" in capsys.readouterr().err


def test_missing_down_revision_refused(tmp_path, capsys):
    scripts = _script_dir(tmp_path, CHAIN[:-1] + [("d0e1f2a3b4c5", "typo_parent")])
    dsn = _db(tmp_path, "d0e1f2a3b4c5")

    assert checker.check(["--dsn", dsn, "--script-dir", str(scripts)]) == 1
    err = capsys.readouterr().err
    assert "missing down_revision chain" in err
    assert "typo_parent" in err


def test_unknown_db_revision_refused(tmp_path, capsys):
    scripts = _script_dir(tmp_path, CHAIN)
    dsn = _db(tmp_path, "deadbeef0000")

    assert checker.check(["--dsn", dsn, "--script-dir", str(scripts)]) == 1
    assert "not in the script directory" in capsys.readouterr().err


def test_multiple_applied_versions_refused(tmp_path, capsys):
    scripts = _script_dir(tmp_path, CHAIN)
    dsn = _db(tmp_path, "b8c9d0e1f2a3", "c9d0e1f2a3b4")

    assert checker.check(["--dsn", dsn, "--script-dir", str(scripts)]) == 1
    assert "multiple versions" in capsys.readouterr().err


def test_dsn_credentials_masked_even_when_db_read_fails(tmp_path, capsys, monkeypatch):
    scripts = _script_dir(tmp_path, CHAIN)

    async def fake_read(dsn):
        raise RuntimeError("auth failed for postgresql://postgres:swordfish@db.internal/aios")

    monkeypatch.setattr(checker, "read_db_head", fake_read)
    dsn = "postgresql+asyncpg://postgres:swordfish@db.internal:5432/aios?password=hunter2"

    assert checker.check(["--dsn", dsn, "--script-dir", str(scripts)]) == 1
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "swordfish" not in combined
    assert "hunter2" not in combined
    assert dsn not in combined
    assert "postgresql+asyncpg://***@db.internal:5432" in out.out


def test_no_dsn_refused_without_printing_anything_secret(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("AIOS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert checker.check(["--script-dir", str(_script_dir(tmp_path, CHAIN))]) == 1
    assert "no database URL" in capsys.readouterr().err


def test_real_repo_scripts_parse_and_keep_expected_chain(tmp_path):
    # Read-only: other work may add heads, so do not assert the current head.
    for path in (ROOT / "alembic" / "versions").glob("*.py"):
        tree = ast.parse(path.read_text())
        checker._literal_assignment(tree, "revision")
        checker._literal_assignment(tree, "down_revision")
    versions = ROOT / "alembic" / "versions"
    grants = ast.parse((versions / "c9d0e1f2a3b4_knowledge_grants.py").read_text())
    vectors = ast.parse((versions / "d0e1f2a3b4c5_knowledge_vectors.py").read_text())
    assert checker._literal_assignment(grants, "down_revision") == "b8c9d0e1f2a3"
    assert checker._literal_assignment(vectors, "down_revision") == "c9d0e1f2a3b4"
