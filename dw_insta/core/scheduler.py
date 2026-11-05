from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .series import Group, SeriesState

# The queue is the source of truth: the next post is the first one still
# pending, in series order. Planned dates are derived from today on every read
# and never stored, so a missed week simply moves everything along instead of
# piling up as overdue, and merging or reordering can't skip a post.


def pending_groups(state: SeriesState) -> list[Group]:
    return [g for g in state.groups if g.is_pending]


def next_group(state: SeriesState) -> Optional[Group]:
    return next((g for g in state.groups if g.is_pending), None)


def posted_on(state: SeriesState, day: date) -> int:
    prefix = day.isoformat()
    return sum(1 for g in state.groups if g.posted_at and g.posted_at.startswith(prefix))


def _first_free_day(state: SeriesState, today: date) -> date:
    """Tomorrow if something already went out today, otherwise today, and
    never before the series' start date."""
    day = today + timedelta(days=1) if posted_on(state, today) else today
    if state.start_date:
        try:
            day = max(day, date.fromisoformat(state.start_date))
        except ValueError:
            pass
    return day


def planned_dates(state: SeriesState, today: Optional[date] = None) -> dict[str, date]:
    """One post per day from the first free day, keyed by group id. Posted
    and skipped groups have no entry."""
    today = today or date.today()
    first = _first_free_day(state, today)
    return {g.id: first + timedelta(days=i) for i, g in enumerate(pending_groups(state))}
