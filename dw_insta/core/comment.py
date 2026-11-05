from __future__ import annotations

from .exif_info import get_camera_line
from .series import Group, SeriesState

# Instagram's per-post limit since December 2025. Tags past it stay stored
# (a limit that moves shouldn't cost you a curated list) but are not copied.
HASHTAG_CAP = 5


def effective_tags(state: SeriesState, group: Group) -> list[str]:
    """Every tag this post carries, in priority order: its own, or the
    series' when it has none of its own."""
    text = group.hashtags if group.hashtags is not None else state.hashtags
    return text.split() if text else []


def compose_comment(state: SeriesState, group: Group) -> str:
    """Join caption (+ optional Japanese translation), an optional EXIF
    gear line, and the first HASHTAG_CAP hashtags into the single block you
    paste into Instagram's caption box."""
    parts = []
    if group.caption:
        parts.append(group.caption)
    if group.caption_ja:
        parts.append(group.caption_ja)

    if state.include_gear_line and group.photos:
        gear_line = get_camera_line(state.out_dir / group.photos[0])
        if gear_line:
            parts.append(gear_line)

    tags = effective_tags(state, group)[:HASHTAG_CAP]
    if tags:
        parts.append(" ".join(tags))

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
    """Bulk-accept every group's primary pending suggested caption. The caller saves."""
    return sum(1 for group in state.groups if accept_caption_suggestion(group))


def accept_all_hashtags_suggestions(state: SeriesState) -> int:
    """Bulk-accept every group's primary pending suggested hashtags. The caller saves."""
    return sum(1 for group in state.groups if accept_hashtags_suggestion(group))
