from __future__ import annotations

from .series import Group, SeriesState


def merge_groups(state: SeriesState, group_ids: list[str]) -> Group:
    """Combine two or more not-yet-posted groups (in the given order) into
    a single carousel post, in-place at the position of the first group."""
    ids = set(group_ids)
    positions = [i for i, g in enumerate(state.groups) if g.id in ids]
    if len(positions) != len(group_ids):
        raise ValueError("one or more group_ids not found")
    targets = [g for g in state.groups if g.id in ids]
    if any(g.is_posted for g in targets):
        raise ValueError("cannot merge a group that's already posted/archived")

    by_id = {g.id: g for g in targets}
    ordered = [by_id[gid] for gid in group_ids]

    merged_photos: list[str] = []
    for g in ordered:
        merged_photos.extend(g.photos)

    merged = Group(id=ordered[0].id, date=ordered[0].date, photos=merged_photos)

    insert_at = min(positions)
    state.groups = [g for g in state.groups if g.id not in ids]
    state.groups.insert(insert_at, merged)
    return merged


def split_group(state: SeriesState, group_id: str, photos_to_split_off: list[str]) -> Group:
    """Pull one or more photos out of an existing group into a new group
    placed immediately after it."""
    idx = next((i for i, g in enumerate(state.groups) if g.id == group_id), None)
    if idx is None:
        raise ValueError(f"group {group_id!r} not found")
    group = state.groups[idx]
    if group.is_posted:
        raise ValueError("cannot split a group that's already posted/archived")

    remaining = [p for p in group.photos if p not in photos_to_split_off]
    split_off = [p for p in group.photos if p in photos_to_split_off]
    if not split_off or not remaining:
        raise ValueError("split must leave photos on both sides")

    group.photos = remaining
    new_group = Group(id=f"{group.id}-split", date=group.date, photos=split_off)
    state.groups.insert(idx + 1, new_group)
    return new_group


def reorder_groups(state: SeriesState, ordered_group_ids: list[str]) -> None:
    """Reorder groups to match ordered_group_ids exactly (drag-to-reorder in the UI)."""
    by_id = {g.id: g for g in state.groups}
    if set(ordered_group_ids) != set(by_id):
        raise ValueError("ordered_group_ids must be a permutation of existing group ids")
    state.groups = [by_id[gid] for gid in ordered_group_ids]
