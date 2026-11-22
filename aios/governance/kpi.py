"""Authoritative KPIs: deterministic Python/SQL calculations. LLMs interpret, never decide."""


def win_rate(closed_won: int, closed_lost: int) -> float:
    total = closed_won + closed_lost
    if total <= 0:
        return 0.0
    return round(closed_won / total, 4)


def conversion_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def average_deal_size(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def interpret_kpis(current: dict[str, float], previous: dict[str, float] | None = None) -> dict:
    """Deterministic narrative over authoritative KPIs; no invented targets.

    Comparisons use the caller's baseline only. An LLM may paraphrase this
    output but must not originate the numbers or the direction.
    """
    previous = previous or {}
    items = []
    declines = []
    for name in sorted(current):
        now = float(current[name])
        if name in previous and float(previous[name]) > 0:
            before = float(previous[name])
            delta = round(now - before, 4)
            direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
            items.append(f"{name}: {now:g} ({direction} {abs(delta):g} vs baseline)")
            if delta < 0:
                declines.append((name, delta / before))
        else:
            items.append(f"{name}: {now:g} (no baseline)")
    watch = min(declines, key=lambda pair: pair[1])[0] if declines else None
    summary = "; ".join(items) if items else "no KPI values"
    if watch:
        summary += f". Largest relative decline: {watch}."
    return {"summary": summary, "items": items, "watch": watch}
