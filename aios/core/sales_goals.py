"""Monthly sales goals + pace tracking (internal tool).

Progress = sum of closed_won deal values whose close_date (or updated_at
fallback) falls in the month vs SalesGoal.target_brl.
"""

import calendar
from datetime import date, datetime

from sqlalchemy import func, or_, select


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def _month_bounds(year_month: str) -> tuple[datetime, datetime]:
    y, m = int(year_month[:4]), int(year_month[5:7])
    start = datetime(y, m, 1)
    if m == 12:
        end = datetime(y + 1, 1, 1)
    else:
        end = datetime(y, m + 1, 1)
    return start, end


# Below this many days into the month, a straight-line projection is noise:
# one large win on day 1 would extrapolate to a full month of it.
_MIN_DAYS_TO_PROJECT = 7


async def set_goal(db, org_id: str, year_month: str, target_brl: float,
                   team_id: str | None = None, created_by: str | None = None):
    """Upsert goal for (org, month, team)."""
    from aios.db.models import SalesGoal

    goal = (await db.execute(select(SalesGoal).where(
        SalesGoal.org_id == org_id,
        SalesGoal.year_month == year_month,
        SalesGoal.team_id == team_id,
    ))).scalars().first()
    if goal:
        goal.target_brl = target_brl
    else:
        goal = SalesGoal(org_id=org_id, year_month=year_month,
                         target_brl=target_brl, team_id=team_id,
                         created_by=created_by)
        db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return goal


async def month_progress(db, org_id: str, year_month: str | None = None,
                         team_id: str | None = None) -> dict:
    """Goal progress + pace. Goal-less months return stats with target 0."""
    from aios.db.models import CrmDeal, SalesGoal

    year_month = year_month or current_month()
    start, end = _month_bounds(year_month)

    goal = (await db.execute(select(SalesGoal).where(
        SalesGoal.org_id == org_id,
        SalesGoal.year_month == year_month,
        SalesGoal.team_id == team_id,
    ))).scalars().first()
    if goal is None and team_id is not None:
        goal = (await db.execute(select(SalesGoal).where(
            SalesGoal.org_id == org_id,
            SalesGoal.year_month == year_month,
            SalesGoal.team_id == None,  # noqa: E711 org-wide fallback
        ))).scalars().first()
    target = goal.target_brl if goal else 0.0

    q = select(
        func.coalesce(func.sum(CrmDeal.value), 0),
        func.count(CrmDeal.id),
    ).where(
        CrmDeal.org_id == org_id,
        CrmDeal.stage == "closed_won",
        or_(
            (CrmDeal.close_date != None) & (CrmDeal.close_date >= start) & (CrmDeal.close_date < end),  # noqa: E711
            (CrmDeal.close_date == None) & (CrmDeal.updated_at >= start) & (CrmDeal.updated_at < end),  # noqa: E711
        ),
    )
    if team_id:
        q = q.where(CrmDeal.team_id == team_id)
    won, count = (await db.execute(q)).one()

    today = date.today()
    days_in_month = calendar.monthrange(int(year_month[:4]), int(year_month[5:7]))[1]
    if year_month == current_month():
        day = today.day
    elif year_month < current_month():
        day = days_in_month
    else:
        day = 0
    expected = target * day / days_in_month if target and day else 0.0
    # Straight-line projection from day 1 is wildly optimistic (one early win
    # projects to a full month of it), so only extrapolate once there is enough
    # of the month to mean anything. Before then, project nothing rather than
    # publish a number Sales would plan against.
    projected = (won / day * days_in_month) if (day and (day >= _MIN_DAYS_TO_PROJECT)) else 0.0
    pct = round(won / target * 100, 1) if target else 0.0

    if not target:
        status = "no_goal"
    elif day == 0:
        # A month that has not started: expected is 0, so the old
        # `won >= expected` test called an untouched future month "ahead".
        status = "not_started"
    elif (won or 0) >= expected:
        status = "ahead"
    else:
        status = "behind"

    return {
        "year_month": year_month,
        "target_brl": target,
        "won_brl": round(won or 0, 2),
        "deals_won": count,
        "day": day,
        "days_in_month": days_in_month,
        "expected_brl": round(expected, 2),
        "pct": pct,
        "projected_brl": round(projected, 2),
        "remaining_brl": round(target - (won or 0), 2) if target else 0.0,
        "status": status,
    }
