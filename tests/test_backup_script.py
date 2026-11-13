"""The daily backup must hand pg_dump a URL it accepts and never store an
empty archive. Both failures were silent in production (20-byte .sql.gz)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backup_strips_asyncpg_suffix_and_writes_non_empty_dump(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pg_dump = bin_dir / "pg_dump"
    pg_dump.write_text('#!/bin/sh\nprintf "%s" "$1" > "$CAPTURE"\nhead -c 400 /dev/urandom | base64\n')
    pg_dump.chmod(0o755)
    capture = tmp_path / "url.txt"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AIOS_DATABASE_URL": "postgresql+asyncpg://u:p@postgres:5432/aios",
        "BACKUP_DIR": str(tmp_path / "backups"),
        "CAPTURE": str(capture),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "deploy" / "backup.sh")],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert capture.read_text() == "postgresql://u:p@postgres:5432/aios"
    assert list((tmp_path / "backups").glob("aios_*.sql.gz"))
