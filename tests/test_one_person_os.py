"""OnePersonOS: scaffold dirs + team-brain sync."""
import os
import tempfile

import pytest

from aios.core.one_person_os import DIRS, scaffold_one_person_os, sync_one_person_os_to_team_brain


def test_scaffold_creates_five_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        out = scaffold_one_person_os(tmp)
        assert [os.path.basename(p) for p in out] == DIRS
        assert all(os.path.isdir(p) for p in out)


def test_scaffold_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        out = scaffold_one_person_os(tmp)
        out2 = scaffold_one_person_os(tmp)
        assert out == out2


@pytest.mark.asyncio
async def test_sync_returns_zero_without_org():
    assert await sync_one_person_os_to_team_brain("/nonexistent", org_id="") == 0
