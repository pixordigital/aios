from __future__ import annotations

import re

_DATE_ISO = re.compile(r"-\d{4}-\d{2}-\d{2}$")
_DATE_SHORT = re.compile(r"-\d{8}$")
_VERSION = re.compile(r"^(.*?)[-_]?v?(\d+(?:\.\d+)*)$")
_EXCLUDED = (":batch", ":free")
_TOL = 1e-6


def _price(model: dict) -> tuple[float, float] | None:
    p = model.get("pricing") or {}
    try:
        return (round(float(p["prompt"]) * 1e6, 4), round(float(p["completion"]) * 1e6, 4))
    except (KeyError, TypeError, ValueError):
        return None


def _base(mid: str) -> str:
    b = str(mid).lower().split(":", 1)[0]
    b = _DATE_ISO.sub("", b)
    return _DATE_SHORT.sub("", b)


def _family(mid: str) -> tuple[str, str]:
    b = _base(mid)
    m = _VERSION.match(b)
    return (m.group(1), m.group(2)) if m else (b, "")


def _provider(mid: str) -> str:
    return _base(mid).split("/", 1)[0]


def _created(model: dict) -> float:
    try:
        return float(model.get("created") or 0)
    except (TypeError, ValueError):
        return 0.0


def diff_catalog(catalog: list[dict], watched: dict[str, tuple[float, float]]) -> dict:
    """Compare a live model catalog against watched id->price pairs."""
    live: dict[str, tuple] = {}
    indexed: list[tuple] = []
    for model in catalog or []:
        mid = model.get("id")
        if not mid or mid.endswith(_EXCLUDED):
            continue
        price = _price(model)
        if price is None:
            continue
        rec = (mid, price, _created(model), _provider(mid), _family(mid), model)
        live[mid] = rec
        indexed.append(rec)

    missing = sorted(set(watched) - set(live))

    price_changed = []
    for mid in sorted(watched):
        if mid not in live:
            continue
        old = tuple(float(x) for x in watched[mid])
        new = live[mid][1]
        if any(abs(a - b) > _TOL for a, b in zip(old, new)):
            price_changed.append({"id": mid, "old": old, "new": new})

    successor_candidates = []
    for mid in sorted(watched):
        known = live[mid][2] if mid in live else 0.0
        family = _family(mid)[0]
        cands = [r for r in indexed if r[0] != mid and r[3] == _provider(mid)
                 and r[4][0] == family and r[2] > known]
        if not cands:
            continue
        best = sorted(cands, key=lambda r: (-r[2], r[0]))[0]
        successor_candidates.append({
            "id": best[0],
            "replaces": mid,
            "price_in": best[1][0],
            "price_out": best[1][1],
            "created": best[5].get("created", 0),
            "canonical_slug": best[5].get("canonical_slug", ""),
        })

    fresh = [r for r in indexed if r[0] not in watched]
    fresh.sort(key=lambda r: (-r[2], r[0]))
    new_models = [
        {"id": r[0], "created": r[5].get("created", 0),
         "price_in": r[1][0], "price_out": r[1][1]}
        for r in fresh[:50]
    ]

    return {
        "missing": missing,
        "price_changed": price_changed,
        "successor_candidates": successor_candidates,
        "new_models": new_models,
    }


def apply_updates(watched: dict[str, tuple[float, float]], diff: dict) -> dict:
    """Return a fresh, sorted watch map with refreshed prices and successors."""
    out = {mid: tuple(float(x) for x in pair) for mid, pair in watched.items()}
    for item in diff.get("price_changed", []):
        out[item["id"]] = tuple(float(x) for x in item["new"])
    for cand in diff.get("successor_candidates", []):
        out[cand["id"]] = (float(cand["price_in"]), float(cand["price_out"]))
    return {mid: out[mid] for mid in sorted(out)}
