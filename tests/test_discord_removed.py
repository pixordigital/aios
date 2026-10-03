"""Discord must not come back as a half-working channel.

It shipped as a dashboard option and a Pro-plan entitlement while `start()`
was `pass`, `send()` returned `None`, and the webhook compared an HMAC-SHA256
hex digest against Discord's Ed25519 header. It has since been removed from the
product; these pin the removal so no dead surface creeps back in.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

CODE_GLOBS = ["aios/**/*.py", "aios/**/*.html", "tests/**/*.py"]


def _files():
    for pattern in CODE_GLOBS:
        yield from ROOT.glob(pattern)


def test_no_module_or_route_remains():
    assert not (ROOT / "aios/channels/discord.py").exists()
    assert not (ROOT / "aios/api/discord_webhook.py").exists()


def test_nothing_imports_it():
    offenders = [
        str(p.relative_to(ROOT))
        for p in _files()
        if "discord" in p.read_text().lower()
        and "discordar" not in p.read_text().lower()
        and "test_no_discord" not in p.name
    ]
    # allow this file and any doc that names the removal in prose
    offenders = [o for o in offenders if o != "tests/test_discord_removed.py"]
    assert not offenders, f"Discord references survive in code: {offenders}"


def test_channel_registry_has_no_discord():
    from aios.channels.manager import CHANNEL_REGISTRY

    assert "discord" not in CHANNEL_REGISTRY


def test_settings_fields_are_gone():
    from aios.config import settings

    for field in ("discord_public_key", "discord_webhook_secret"):
        assert not hasattr(settings, field), f"settings.{field} still exists"


def test_plans_do_not_sell_it():
    from aios.config import PLANS

    for name, plan in PLANS.items():
        assert "discord" not in (plan.get("channels") or []), (
            f"plan {name} still lists discord as an entitlement"
        )


def test_dashboard_does_not_offer_it():
    app = (ROOT / "aios/dashboard/app.py").read_text()
    for template in ("channels.html", "channel_form.html"):
        t = (ROOT / "aios/dashboard/templates" / template).read_text()
        assert "discord" not in t.lower(), f"{template} still offers Discord"


def test_router_is_not_mounted():
    src = (ROOT / "aios/main.py").read_text()
    assert "discord" not in src.lower()


def test_deactivation_migration_exists():
    """A still-active row would log a traceback on every restart, because
    main.py starts every active channel and build() raises on an unknown type.
    Credentials stay in the row, deactivated, rather than being dropped."""
    migrations = list((ROOT / "alembic/versions").glob("*discord*.py"))
    assert migrations, "no migration deactivates existing discord channel rows"
    body = migrations[0].read_text()
    assert "is_active = false" in body
    assert "channel_type = 'discord'" in body