"""Wire team channels against a fake DB/session.

No live services, no conftest fixtures, no prod writes. Covers the safety
invariants: explicit mapping, dry-run default, backup-before-mutation, field
scope, ownership/ambiguity refusal, and idempotence.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "wire_team_channels", ROOT / "scripts" / "wire_team_channels.py"
)
wtc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = wtc
_spec.loader.exec_module(wtc)

ORG = "org-a"


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class FakeChannel(SimpleNamespace):
    def __init__(self, **kwargs):
        object.__setattr__(self, "writes", [])
        for key, value in kwargs.items():
            object.__setattr__(self, key, value)

    def __setattr__(self, name, value):
        if name in {"team_id", "is_active"}:
            self.writes.append((name, value, Path(self.backup_exists_path).exists()))
        object.__setattr__(self, name, value)


class FakeDB:
    def __init__(self, channels, teams):
        self.channels = list(channels)
        self.teams = list(teams)
        self.commits = 0

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is wtc.ChannelConnection:
            return FakeResult(self.channels)
        if entity is wtc.Team:
            return FakeResult(self.teams)
        raise AssertionError(f"unexpected statement: {stmt}")

    async def commit(self):
        self.commits += 1


def channel(label, team_id=None, is_active=True, org_id=ORG, ident=None, token="t0ken"):
    return FakeChannel(
        id=ident or f"ch-{label}",
        org_id=org_id,
        label=label,
        channel_type="slack",
        config={"bot_token": f"xoxb-{token}"},
        is_active=is_active,
        team_id=team_id,
        backup_exists_path="/nonexistent/backup.json",
    )


def team(name, ident=None, org_id=ORG):
    return SimpleNamespace(id=ident or f"team-{name}", org_id=org_id, name=name)


def sample_db():
    return FakeDB(
        channels=[
            channel("#dept-data", team_id=None, is_active=True, ident="ch-data"),
            channel("#red-team", team_id="team-red", is_active=False, ident="ch-red"),
        ],
        teams=[team("data", "team-data"), team("red", "team-red")],
    )


def mapping():
    return {
        "#dept-data": {"team": "data", "is_active": True},
        "#red-team": {"team": "red", "is_active": True},
    }


class TestMappingValidation:
    def test_inline_json_and_python_mapping_agree(self):
        obj = mapping()
        assert wtc.normalize_mapping(obj) == wtc.normalize_mapping(json.dumps(obj))

    @pytest.mark.parametrize(
        "bad",
        [
            {},
            {"#x": "data"},
            {"#x": {"team": "data"}},
            {"#x": {"team": "data", "is_active": "true"}},
            {"#x": {"team": "data", "team_id": "id", "is_active": True}},
            {"#x": {"nope": "data", "is_active": True}},
            {"#x": {"team": "", "is_active": True}},
        ],
    )
    def test_rejects_bad_specs(self, bad):
        with pytest.raises(wtc.WireError):
            wtc.normalize_mapping(bad)

    def test_team_id_form(self):
        spec = wtc.normalize_mapping({"#x": {"team_id": "team-data", "is_active": False}})
        assert spec["#x"].team_id == "team-data"
        assert spec["#x"].team_key is None

    def test_cli_defaults_to_dry_run(self):
        parser = wtc.build_parser()
        args = parser.parse_args(["--org-id", ORG, "--mapping", "{}"])
        assert args.apply is False
        assert parser.parse_args(["--org-id", ORG, "--mapping", "{}", "--apply"]).apply is True
        with pytest.raises(SystemExit):
            parser.parse_args(["--org-id", ORG, "--mapping", "{}", "--dry-run", "--apply"])


class TestDryRun:
    def test_no_writes_no_backup_no_tokens(self, capsys, tmp_path):
        db = sample_db()
        plan = asyncio.run(wtc.build_plan(db, ORG, mapping()))
        assert [c.changed for c in plan] == [True, True]

        code = asyncio.run(wtc.execute_plan(db, ORG, plan, apply=False))
        out = capsys.readouterr().out
        assert code == 0
        assert "DRY-RUN: 2 of 2" in out
        assert "xoxb" not in out
        assert "t0ken" not in out
        assert db.commits == 0
        assert [c.channel.writes for c in plan] == [[], []]
        assert not (tmp_path / "backup.json").exists()


class TestApply:
    def test_backup_before_mutation_and_only_two_fields_change(self, capsys, tmp_path):
        db = sample_db()
        plan = asyncio.run(wtc.build_plan(db, ORG, mapping()))
        backup = tmp_path / "backup.json"
        for change in plan:
            change.channel.backup_exists_path = str(backup)

        code = asyncio.run(
            wtc.execute_plan(db, ORG, plan, apply=True, backup=backup)
        )
        assert code == 0
        assert db.commits == 1
        assert "APPLY: committed 2 row(s)." in capsys.readouterr().out

        # Backup snapshot predates both assignments and omits config/token.
        assert all(name in {"team_id", "is_active"} for c in plan for name, _, _ in c.channel.writes)
        assert all(exists is True for c in plan for _, _, exists in c.channel.writes)
        saved = json.loads(backup.read_text())
        assert saved["org_id"] == ORG
        assert [row["team_id"] for row in saved["rows"]] == [None, "team-red"]
        assert [row["is_active"] for row in saved["rows"]] == [True, False]
        assert "xoxb" not in backup.read_text()
        assert oct(backup.stat().st_mode & 0o777) == "0o600"

        before = {id(c.channel): dict(vars(c.channel)) for c in plan}
        for c in plan:
            if "writes" in before[id(c.channel)]:
                del before[id(c.channel)]["writes"]
        after = {id(c.channel): dict(vars(c.channel)) for c in plan}
        for key in after:
            after[key].pop("writes", None)
            changed = {k for k in before[key] if before[key][k] != after[key][k]}
            assert changed <= {"team_id", "is_active"}

        assert plan[0].channel.team_id == "team-data"
        assert plan[0].channel.is_active is True
        assert plan[1].channel.team_id == "team-red"
        assert plan[1].channel.is_active is True
        assert plan[0].channel.config == {"bot_token": "xoxb-t0ken"}

    def test_rerun_is_noop_without_second_backup_or_commit(self, capsys, tmp_path):
        db = sample_db()
        first = asyncio.run(wtc.build_plan(db, ORG, mapping()))
        backup = tmp_path / "backup.json"
        for change in first:
            change.channel.backup_exists_path = str(backup)
        asyncio.run(wtc.execute_plan(db, ORG, first, apply=True, backup=backup))

        second = asyncio.run(wtc.build_plan(db, ORG, mapping()))
        assert all(not c.changed for c in second)
        writes_before = [len(c.channel.writes) for c in second]
        code = asyncio.run(
            wtc.execute_plan(db, ORG, second, apply=True, backup=backup)
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "no changes" in out
        assert db.commits == 1
        assert [len(c.channel.writes) for c in second] == writes_before


class TestRefusals:
    @pytest.mark.parametrize(
        "bad_map,message",
        [
            ({"#missing": {"team": "data", "is_active": True}}, "unknown channel label"),
            ({"#dept-data": {"team": "nope", "is_active": True}}, "unknown team key"),
            (
                {"#dept-data": {"team_id": "team-nope", "is_active": True}},
                "unknown team id",
            ),
        ],
    )
    def test_unknown_label_or_team_no_mutation(self, bad_map, message, tmp_path):
        db = sample_db()
        with pytest.raises(wtc.WireError, match=message):
            asyncio.run(wtc.build_plan(db, ORG, bad_map))
        assert db.commits == 0
        assert not (tmp_path / "backup.json").exists()
        assert all(not c.writes for c in db.channels)

    def test_cross_org_channel_and_team_refused(self):
        db = FakeDB(
            channels=[channel("#dept-data", org_id="org-b")],
            teams=[team("data", "team-data", org_id="org-b")],
        )
        with pytest.raises(wtc.WireError, match="belongs to another org"):
            asyncio.run(wtc.build_plan(db, ORG, mapping()))
        assert db.commits == 0

    def test_duplicate_label_and_team_name_refused(self):
        db = FakeDB(
            channels=[
                channel("#dept-data", ident="ch-1"),
                channel("#dept-data", ident="ch-2"),
            ],
            teams=[team("data", "team-1"), team("data", "team-2")],
        )
        with pytest.raises(wtc.WireError, match="ambiguous channel label"):
            asyncio.run(wtc.build_plan(db, ORG, mapping()))
        db.channels.pop()
        with pytest.raises(wtc.WireError, match="ambiguous team key"):
            asyncio.run(wtc.build_plan(db, ORG, mapping()))

    def test_backup_path_collision_refuses_before_mutation(self, tmp_path):
        db = sample_db()
        plan = asyncio.run(wtc.build_plan(db, ORG, mapping()))
        backup = tmp_path / "exists.json"
        backup.write_text("{}")
        with pytest.raises(FileExistsError):
            asyncio.run(wtc.execute_plan(db, ORG, plan, apply=True, backup=backup))
        assert db.commits == 0
        assert all(not c.channel.writes for c in plan)
