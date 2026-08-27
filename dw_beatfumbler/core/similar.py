from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API_URL = "https://ws.audioscrobbler.com/2.0/"

# Strips "(Official Video)", "[Lyrics]", "ft. X", etc. that YouTube titles
# carry but Last.fm's track database never does — left in, they turn an
# exact-ish match into a miss.
_BRACKETED = re.compile(r"[\(\[][^\)\]]*[\)\]]")
_JUNK_WORDS = re.compile(
    r"\b(official\s*(music\s*)?(video|audio)?|lyrics?|visualizer|hd|hq|remaster(ed)?)\b",
    re.IGNORECASE,
)
_FEAT = re.compile(r"\b(feat\.?|ft\.?|featuring)\b.*$", re.IGNORECASE)


class SimilarError(Exception):
    pass


def clean_title(title: str) -> str:
    """Best-effort strip of YouTube-upload cruft from a track title before
    it's used as a Last.fm search query. Falls back to the original text if
    cleaning would empty it out entirely."""
    cleaned = _BRACKETED.sub(" ", title)
    cleaned = _FEAT.sub(" ", cleaned)
    cleaned = _JUNK_WORDS.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—|")
    return cleaned or title


@dataclass
class SimilarTrack:
    artist: str
    title: str
    match: float  # Last.fm's 0-1 similarity score


def fetch_similar(artist: str, title: str, api_key: str, limit: int = 15) -> list[SimilarTrack]:
    """Query Last.fm's track.getSimilar for tracks close to (artist, title).
    autocorrect=1 lets Last.fm fix minor spelling/casing drift, common in
    titles pulled straight from YouTube uploads."""
    if not api_key:
        raise SimilarError("No Last.fm API key configured.")

    params = {
        "method": "track.getsimilar",
        "artist": artist,
        "track": title,
        "api_key": api_key,
        "format": "json",
        "limit": str(limit),
        "autocorrect": "1",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SimilarError(f"Network error: {exc}") from exc

    if data.get("error"):
        raise SimilarError(data.get("message", f"Last.fm error {data['error']}"))

    tracks = data.get("similartracks", {}).get("track", [])
    return [
        SimilarTrack(artist=t["artist"]["name"], title=t["name"], match=float(t.get("match", 0)))
        for t in tracks
    ]
