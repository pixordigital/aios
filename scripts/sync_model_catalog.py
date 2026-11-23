"""Sync watched model prices with the live OpenRouter catalog."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aios.core.model_catalog_sync import apply_updates, diff_catalog
from aios.core.model_select import fetch_catalog

PRICES_PATH = ROOT / "aios" / "data" / "model_prices.json"
REPORT_KEYS = ("missing", "price_changed", "successor_candidates", "new_models")


def _ids(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        if "id" in value:
            return [str(value["id"])]
        out = []
        for key, child in value.items():
            for item in _ids(child):
                out.append(f"{key} → {item}" if item != str(key) else str(key))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for child in value:
            out.extend(_ids(child))
        return out
    return [str(value)]


async def main() -> None:
    raw = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    watched = {k: tuple(v) for k, v in raw.items()}
    catalog = await fetch_catalog(force=True)
    diff = diff_catalog(catalog, watched)
    updated = apply_updates(watched, diff)

    text = json.dumps(updated, indent=2, sort_keys=True) + "\n"
    PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=PRICES_PATH.parent, prefix=".model_prices-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, PRICES_PATH)
    except BaseException:
        os.unlink(tmp)
        raise

    print("## Model catalog drift")
    for key in REPORT_KEYS:
        value = diff.get(key, [])
        ids = _ids(value)
        count = len(value) if isinstance(value, (dict, list, tuple, set)) else len(ids)
        print(f"- {key}: {count}")
    for key in REPORT_KEYS:
        ids = _ids(diff.get(key, []))
        if ids:
            print(f"- {key} ids: " + ", ".join(f"`{item}`" for item in ids))


if __name__ == "__main__":
    asyncio.run(main())
