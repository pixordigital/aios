"""money-update: one-shot money/status check for BusinessOS (exits 0/1)."""
import asyncio
import sys
from datetime import date


async def _orgs():
    from sqlalchemy import select

    from aios.db.models import Organization

    async with None:  # placeholder — replaced below
        pass


async def main() -> int:
    """Print org money status; returns 0 if at/below budget, 1 if over."""
    from aios.core.limits import get_monthly_usage
    from aios.db.backend import db_session
    from aios.db.models import Organization
    from sqlalchemy import select

    try:
        async with db_session() as db:
            orgs = (await db.execute(select(Organization))).scalars().all()
    except Exception:
        orgs = []

    if not orgs:
        print(f"total_cost=0.0 over_budget=false date={date.today().isoformat()}")
        return 0

    status = []
    over = False
    for org in orgs:
        try:
            async with db_session() as db:
                usage = await get_monthly_usage(org.id, db)
        except Exception:
            usage = {}
        org_over = bool(usage.get("over_limit") or usage.get("over_budget"))
        status.append(f"org={org.id} total_cost={usage.get('total_cost_usd', 0)} over_budget={org_over}")
        over = over or org_over
    print(" | ".join(status) + f" date={date.today().isoformat()}")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
