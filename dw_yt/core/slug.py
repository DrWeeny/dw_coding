from __future__ import annotations

import re
import unicodedata


def slugify(text: str) -> str:
    """ASCII, lowercase, underscore-separated version of text — safe for
    any filesystem or tool. The original text is kept as the display title
    in the database, this is only ever used for the on-disk filename."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return slug or "track"


def slug_filename(title: str, video_id: str, suffix: str) -> str:
    """Build the on-disk filename for a track: slugified title plus the
    (lowercased) video id for uniqueness, when one is known."""
    id_part = video_id.lower() if video_id else ""
    stem = f"{slugify(title)}_{id_part}" if id_part else slugify(title)
    return f"{stem}{suffix}"
