"""Offline tests for the owner-DM wiring CLI.

Fake DB + fake config, no live Slack, no conftest fixtures. Run with:
    pytest --noconftest tests/test_wire_owner_dm.py
"""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import wire_owner_dm as cli  # noqa: E402

from aios.config import settings  # noqa: E402
from aios.core.secrets import decrypt_channel_config, encrypt_channel_config  # noqa: E402
from aios.db.models import ChannelConnection, Organization  # noqa: E402

ORG = "8c4f36ec-14f1-494d-91dd-c3366b9523ee"
USER = "U123ABC"
TOKEN = "xoxb-plain-secret-token"
CHANNEL_ID = "D1234567890"
LABEL = "Slack 1:1 sales"


@pytest.fixture(autouse=True)
def _test_secrets(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-jwt-secret", raising=False)
    monkeypatch.setattr(settings, "encryption_key", "", raising=False)


@pytest.fixture(autouse=True)
def _no_slack_calls(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("wire_owner_dm must not call the Slack API")

    monkeypatch.setattr("aios.core.meetings.post_to_slack", boom)


def make_conn(conn_id="conn-1", label=LABEL, channel_type="slack", active=True,
              config=None):
    cfg = config if config is not None else {
        "slack_channel_id": CHANNEL_ID,
        "bot_token": TOKEN,
    }
    return ChannelConnection(
        id=conn_id,
        org_id=ORG,
        label=label,
        channel_type=channel_type,
        config=encrypt_channel_config(cfg) if cfg else {},
        is_active=active,
    )


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class FakeDB:
    def __init__(self, conns=None, orgs=None):
        self.conns = list(conns) if conns is not None else [make_conn()]
        self.orgs = list(orgs) if orgs is not None else [
            Organization(id=ORG, name="Pixor", slug="pixor")
        ]
        self.commits = 0
        self.rollbacks = 0
        self._snapshot = self._configs()

    def _configs(self):
        return {c.id: dict(c.config or {}) for c in self.conns}

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        return FakeResult(self.orgs if entity is Organization else self.conns)

    async def commit(self):
        self.commits += 1
        self._snapshot = self._configs()

    async def rollback(self):
        self.rollbacks += 1
        for conn in self.conns:
            if conn.id in self._snapshot:
                conn.config = dict(self._snapshot[conn.id])

    def config(self):
        return decrypt_channel_config(self.conns[0].config or {})


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(cli, "real_db_session", session)
    return db


def args(channel=LABEL, *extra):
    return ["--org-id", ORG, "--channel", channel,
            "--slack-user-id", USER, *extra]


def test_dry_run_is_default_no_write_and_masks_secrets(fake_db, capsys):
    rc = cli.main(args())

    out = capsys.readouterr().out
    report = json.loads(out)
    assert rc == 0
    assert report["mode"] == "dry-run"
    assert report["verified_dm_targets"] == 1
    assert fake_db.commits == 0
    assert fake_db.rollbacks == 1
    assert fake_db.config() == {"slack_channel_id": CHANNEL_ID, "bot_token": TOKEN}
    assert TOKEN not in out
    assert "enc:" not in out
    assert USER not in out
    assert report["slack_user_id"].endswith(USER[-4:])


def test_apply_writes_backup_then_is_idempotent(fake_db, tmp_path, capsys):
    backup = tmp_path / "backup.json"

    rc = cli.main(args(LABEL, "--apply", "--backup", str(backup)))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["mode"] == "apply"
    assert fake_db.commits == 1

    raw = backup.read_text()
    stored = json.loads(raw)["connection"]
    assert stored["id"] == fake_db.conns[0].id
    assert stored["config"]["bot_token"].startswith("enc:")
    assert "slack_1on1" not in stored["config"]
    assert USER not in raw
    assert TOKEN not in raw
    assert oct(backup.stat().st_mode & 0o777) == "0o600"

    cfg = fake_db.config()
    assert cfg["slack_1on1"] is True
    assert cfg["slack_user_id"] == USER
    assert cfg["bot_token"] == TOKEN

    second = tmp_path / "second.json"
    rc = cli.main(args(LABEL, "--apply", "--backup", str(second)))
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "unchanged"
    assert fake_db.commits == 1
    assert not second.exists()


def test_matches_by_connection_id(fake_db, capsys):
    rc = cli.main(args("conn-1"))

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["connection"]["id"] == "conn-1"


def test_refuses_ambiguous_label(fake_db, capsys):
    fake_db.conns.append(make_conn(conn_id="conn-2"))

    rc = cli.main(args())

    err = capsys.readouterr().err
    assert rc == 2
    assert "ambiguous" in err
    assert fake_db.commits == 0
    assert fake_db.rollbacks == 0


def test_refuses_wrong_type_and_unknown_org(fake_db, capsys):
    fake_db.conns[0].channel_type = "evolution"
    assert cli.main(args()) == 2
    assert "not slack" in capsys.readouterr().err

    fake_db.conns[0].channel_type = "slack"
    fake_db.orgs = []
    assert cli.main(args()) == 2
    assert "org not found" in capsys.readouterr().err
    assert fake_db.commits == 0


def test_verification_failure_rolls_back_and_restores_session(fake_db, monkeypatch, capsys):
    import aios.db.backend as backend

    async def no_targets(*a, **k):
        return []

    saved = backend.db_session
    monkeypatch.setattr(cli, "human_slack_targets", no_targets)

    rc = cli.main(args(LABEL, "--apply"))

    assert rc == 2
    assert "verification failed" in capsys.readouterr().err
    assert fake_db.commits == 0
    assert fake_db.rollbacks == 1
    assert backend.db_session is saved


def test_invalid_user_id_and_explicit_dry_run(fake_db, capsys):
    assert cli.main(["--org-id", ORG, "--channel", LABEL,
                     "--slack-user-id", "not-a-slack-id"]) == 2
    assert "Slack user ID" in capsys.readouterr().err

    rc = cli.main(args(LABEL, "--dry-run"))
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"


def test_apply_and_dry_run_are_mutually_exclusive(fake_db):
    with pytest.raises(SystemExit) as exc:
        cli.main(args(LABEL, "--apply", "--dry-run"))
    assert exc.value.code == 2
