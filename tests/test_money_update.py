"""money_update: prints money status, exit 0 ok / 1 over budget."""
import sys

import pytest

from aios.core import money_update


@pytest.mark.asyncio
async def test_main_no_orgs_returns_0(monkeypatch):
    import contextlib

    class _DB:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            class _R:
                def scalars(self):
                    class _S:
                        def all(self):
                            return []

                    return _S()

            return _R()

    monkeypatch.setattr("aios.db.backend.db_session", lambda: _DB(), raising=False)
    assert await money_update.main() == 0


if __name__ == "__main__":
    sys.exit(0)
