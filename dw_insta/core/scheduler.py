from __future__ import annotations

from datetime import date
from typing import Optional

from .series import Group, SeriesState


def today_index(state: SeriesState, today: Optional[date] = None) -> Optional[int]:
    if not state.groups or state.start_date is None:
        return None
    today = today or date.today()
    start = date.fromisoformat(state.start_date)
    elapsed = max(0, (today - start).days)
    return min(elapsed, len(state.groups) - 1)


def today_group(state: SeriesState, today: Optional[date] = None) -> Optional[Group]:
    idx = today_index(state, today)
    return None if idx is None else state.groups[idx]


def overdue_groups(state: SeriesState, today: Optional[date] = None) -> list[Group]:
    """Groups whose scheduled slot has already passed but were never archived."""
    idx = today_index(state, today)
    if idx is None:
        return []
    return [g for g in state.groups[: idx + 1] if not g.is_posted]
