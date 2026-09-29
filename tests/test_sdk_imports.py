"""SDK import smoke tests.

Regression: aios/sdk/client.py defined ``async def list(self)`` on classes that
also used ``list[str]`` annotations. Class-body name binding meant the method
shadowed the builtin, so the *next* method's annotation raised
TypeError: 'function' object is not subscriptable at class-definition time —
the whole aios.sdk package was unimportable.
"""

import importlib
import pkgutil

import aios


def test_sdk_client_imports():
    from aios.sdk.client import TeamsAPI, AgentsAPI, ConversationsAPI  # noqa: F401


def test_all_aios_modules_import():
    """Every module must import cleanly; broken ones are silent runtime bombs."""
    failed = []
    for m in pkgutil.walk_packages(aios.__path__, "aios."):
        try:
            importlib.import_module(m.name)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{m.name}: {type(e).__name__}: {str(e)[:100]}")
    assert not failed, "modules failed to import:\n" + "\n".join(failed)


def test_list_method_does_not_shadow_builtin_in_annotations():
    """A .list() method must not break a later list[...] annotation."""
    from typing import get_type_hints

    from aios.sdk.client import TeamsAPI

    hints = get_type_hints(TeamsAPI.assign_agents)
    assert "list" in str(hints["agent_ids"])
