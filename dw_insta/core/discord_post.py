from __future__ import annotations

from pathlib import Path

import requests

DEFAULT_TIMEOUT = 15


def post_photo_to_discord(webhook_url: str, photo_path: Path, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Post a single photo to a Discord channel via an incoming webhook —
    just the image, no caption. Raises requests.RequestException (including
    HTTPError from a non-2xx response) so the caller can surface it."""
    with open(photo_path, "rb") as f:
        response = requests.post(webhook_url, files={"file": (photo_path.name, f)}, timeout=timeout)
    response.raise_for_status()
