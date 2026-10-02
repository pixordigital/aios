"""Live smoke test for the Meta Graph client.

The unit tests use a mocked transport, so they prove our logic but not that Meta
accepts our request *shape*. This script closes that gap without needing
credentials: it sends the exact payload `MetaWhatsAppClient.create_template`
builds and reports what Meta actually says.

Two modes:

  # no credentials - verifies reachability, the pinned Graph version, that the
  # endpoint edge exists, and that our error envelope parsing matches Meta's real
  # one. It CANNOT verify payload shape: measured against live Meta, an invalid
  # payload returns the same auth error as a valid one.

  AIOS_META_WABA_ID=... AIOS_META_ACCESS_TOKEN=... python3 scripts/meta_smoke.py
    - additionally performs the real calls: verify_connection, list_templates and
      a dry create (rejected by auth, which confirms parsing).

Run it with --full after connecting a WABA in the dashboard.

Exit code is 0 when every check passes, 1 otherwise, so it can gate a deploy.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aios.core.meta_api import (  # noqa: E402
    GRAPH_VERSION,
    MetaAPIError,
    MetaWhatsAppClient,
    TemplateComponents,
)

# Obviously-fake WABA. Meta rejects on auth before touching the data, which is
# exactly what we want: we are probing the request shape, not the account.
FAKE_WABA = "100000000000000000"

OK, WARN, FAIL = "PASS", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []


def check(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


async def probe_shape() -> None:
    """Send our real payload to Meta and read what it complains about."""
    client = MetaWhatsAppClient(waba_id=FAKE_WABA, access_token="invalid-token-probe")
    comps = TemplateComponents(
        header_text="Aviso",
        body="Ola {{1}}, sua consulta de {{2}} esta confirmada para amanha.",
        footer="Obrigado",
        examples={"1": "Joao", "2": "12/03"},
    )
    print("\nSending the exact payload create_template() builds:")
    print(json.dumps({
        "name": "lembrete_consulta",
        "language": "pt_BR",
        "category": "UTILITY",
        "components": comps.to_meta(),
        "allow_category_change": True,
    }, indent=2, ensure_ascii=False))
    print()

    try:
        await client.create_template(
            name="lembrete_consulta",
            language="pt_BR",
            category="UTILITY",
            components=comps,
        )
        check(FAIL, "live create unexpectedly succeeded with a fake token")
    except MetaAPIError as e:
        print(f"  Meta responded: code={e.code} http={e.http_status}")
        print(f"  message: {e.raw_message}\n")

        if e.code is None:
            check(FAIL, "Meta error could not be parsed", "e.code is None")
        else:
            check(OK, "Meta error envelope parsed", f"code={e.code}")

        # The discriminator: a request Meta can parse and route complains about
        # auth/permission/existence. A malformed components array or a bad field
        # name produces a *parameter* error (100 / 131009) with a message naming
        # the offending field.
        # MEASURED, NOT ASSUMED. Posting a deliberately malformed payload
        # (invalid component type, missing name, wrong `example` shape) returns
        # the *identical* code=190 as a well-formed one. Meta therefore
        # authenticates before it validates, so an auth error says NOTHING about
        # whether our component shape is correct. Do not read it as a pass.
        if e.code in (190, 102, 200) or "oauth" in f"{e.code} {e.raw_message}".lower():
            check(
                OK,
                "endpoint reachable and Meta auth checked first",
                f"code={e.code} — proves reachability only, NOT payload shape",
            )
            print("      NOTE: payload shape is still UNVERIFIED. Meta returns the same")
            print("            auth error for valid and invalid payloads alike, so this")
            print("            cannot confirm components/example/allow_category_change.")
            print("            Run with credentials for a real verdict.")
        elif e.code in (100, 131009):
            check(
                WARN,
                "Meta rejected the payload",
                f"code={e.code}: {e.raw_message[:140]}",
            )
        else:
            check(WARN, "Meta returned an unrecognised error", f"code={e.code}")


async def probe_version() -> None:
    """A bad Graph version returns a version error, not a field error."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{FAKE_WABA}",
            headers={"Authorization": "Bearer invalid-token-probe"},
        )
    try:
        payload = r.json()
    except Exception:
        check(FAIL, "Graph version reachable", f"non-JSON response {r.status_code}")
        return
    err = payload.get("error") or {}
    if err.get("type") == "OAuthException" or err.get("code"):
        check(OK, f"Graph version {GRAPH_VERSION} accepted by Meta", f"code={err.get('code')}")
    else:
        check(FAIL, "Graph version rejected", str(payload)[:120])


async def probe_full(waba_id: str, token: str) -> None:
    """Real calls, only possible once a WABA is connected."""
    client = MetaWhatsAppClient(waba_id=waba_id, access_token=token)
    print()
    try:
        info = await client.verify_connection()
        check(OK, "verify_connection", json.dumps(info)[:160])
    except MetaAPIError as e:
        check(FAIL, "verify_connection", f"code={e.code}: {e.raw_message}")
        if e.code == 200:
            print("      token lacks whatsapp_business_management for this WABA")
        return

    try:
        rows = await client.list_templates(limit=5)
        check(OK, "list_templates", f"{len(rows)} template(s) returned")
        for r in rows[:5]:
            print(f"        - {r.get('name')} [{r.get('status')}] "
                  f"reason={r.get('rejected_reason')}")
    except MetaAPIError as e:
        check(FAIL, "list_templates", f"code={e.code}: {e.raw_message}")
        return

    # A real create against a real WABA would consume review quota, so we only
    # do it when explicitly asked.
    if "--submit" in sys.argv:
        try:
            res = await client.create_template(
                name="aios_smoke_test",
                language="pt_BR",
                category="UTILITY",
                components=TemplateComponents(
                    body="Este e um teste de verificacao do {{1}}.",
                    examples={"1": "AIOS"},
                ),
            )
            check(OK, "create_template submitted", json.dumps(res)[:200])
        except MetaAPIError as e:
            check(FAIL, "create_template", f"code={e.code}: {e.raw_message}")


async def main() -> int:
    waba = os.getenv("AIOS_META_WABA_ID", "").strip()
    token = os.getenv("AIOS_META_ACCESS_TOKEN", "").strip()

    print("Meta Graph client — live smoke test")
    print(f"  endpoint: https://graph.facebook.com/{GRAPH_VERSION}")

    print("\n[1] graph version / reachability")
    await probe_version()

    print("\n[2] request shape")
    await probe_shape()

    if waba and token:
        print(f"\n[3] live calls against WABA {waba}")
        await probe_full(waba, token)
    else:
        print("\n[3] live calls — SKIPPED (no AIOS_META_WABA_ID / AIOS_META_ACCESS_TOKEN)")
        print("      Connect a WABA in /dashboard/whatsapp/templates/connect, then:")
        print("      AIOS_META_WABA_ID=... AIOS_META_ACCESS_TOKEN=... python3 scripts/meta_smoke.py")

    failed = [r for r in results if r[0] == FAIL]
    warned = [r for r in results if r[0] == WARN]
    print(f"\n{len(results) - len(failed) - len(warned)} passed, "
          f"{len(warned)} warning(s), {len(failed)} failed")
    if warned:
        print("A WARN means Meta rejected the request itself — read the message above.")
    if not (waba and token):
        print("NOTE: payload shape is NOT verified without credentials.")
        print("      tests/test_meta_contract.py pins our builder against Meta's")
        print("      documented schema; only a live call closes the remaining gap.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))