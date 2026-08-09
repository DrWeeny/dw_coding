from __future__ import annotations

from .exif_info import get_camera_line
from .series import Group, SeriesState


def compose_comment(state: SeriesState, group: Group) -> str:
    """Join caption (+ optional Japanese translation), an optional EXIF
    gear line, and hashtags into the single block you paste into
    Instagram's caption box."""
    parts = []
    if group.caption:
        parts.append(group.caption)
    if group.caption_ja:
        parts.append(group.caption_ja)

    if state.include_gear_line and group.photos:
        gear_line = get_camera_line(state.out_dir / group.photos[0])
        if gear_line:
            parts.append(gear_line)

    tags = group.hashtags if group.hashtags is not None else state.hashtags
    if tags:
        parts.append(tags)

    return "\n\n".join(parts)


def accept_caption_suggestion(group: Group) -> None:
    if group.suggested_caption is not None:
        group.caption = group.suggested_caption
        group.suggested_caption = None


def accept_hashtags_suggestion(group: Group) -> None:
    if group.suggested_hashtags is not None:
        group.hashtags = group.suggested_hashtags
        group.suggested_hashtags = None


def accept_all_caption_suggestions(state: SeriesState) -> int:
    """Bulk-accept every pending suggested_caption. Saves once if anything changed."""
    count = 0
    for group in state.groups:
        if group.suggested_caption is not None:
            accept_caption_suggestion(group)
            count += 1
    if count:
        state.save()
    return count


def accept_all_hashtags_suggestions(state: SeriesState) -> int:
    """Bulk-accept every pending suggested_hashtags. Saves once if anything changed."""
    count = 0
    for group in state.groups:
        if group.suggested_hashtags is not None:
            accept_hashtags_suggestion(group)
            count += 1
    if count:
        state.save()
    return count
