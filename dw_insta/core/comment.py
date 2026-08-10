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


def accept_caption_suggestion(group: Group, filename: str | None = None) -> bool:
    """Accept a pending suggested caption as the group's confirmed caption.
    Defaults to the earliest-in-post-order photo with a pending suggestion;
    pass filename to accept a specific photo's suggestion instead (e.g. from
    the Today widget, where the pink dot tracks whichever photo is
    currently selected in the carousel). Returns whether anything changed."""
    if filename is None:
        pending = group.primary_suggested_caption()
        if pending is None:
            return False
        filename, text = pending
    else:
        text = group.suggested_captions.get(filename)
        if text is None:
            return False
    group.caption = text
    del group.suggested_captions[filename]
    return True


def accept_hashtags_suggestion(group: Group, filename: str | None = None) -> bool:
    if filename is None:
        pending = group.primary_suggested_hashtags()
        if pending is None:
            return False
        filename, text = pending
    else:
        text = group.suggested_hashtags.get(filename)
        if text is None:
            return False
    group.hashtags = text
    del group.suggested_hashtags[filename]
    return True


def accept_all_caption_suggestions(state: SeriesState) -> int:
    """Bulk-accept every group's primary pending suggested caption. Saves once if anything changed."""
    count = sum(1 for group in state.groups if accept_caption_suggestion(group))
    if count:
        state.save()
    return count


def accept_all_hashtags_suggestions(state: SeriesState) -> int:
    """Bulk-accept every group's primary pending suggested hashtags. Saves once if anything changed."""
    count = sum(1 for group in state.groups if accept_hashtags_suggestion(group))
    if count:
        state.save()
    return count
