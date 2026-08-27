from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import yt_dlp

from core.similar import clean_title

WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"

# Wikipedia song ledes often insert a nationality + role between "by" and the
# actual name ("... is a song by American singer Taylor Swift") — skip that
# descriptor clause so the capture is the artist name, not the description.
_DESCRIPTOR = r"(?:[A-Z][a-z]+\s+)?(?:singer(?:-songwriter)?|rapper|musician|band|group|duo|songwriter|artist|producer|DJ|vocalist)\s+"
_BY = re.compile(
    rf"\bis an? (?:song|single|track)\b.{{0,60}}?\bby (?:{_DESCRIPTOR})?"
    r"([A-Z][\w&.,' -]+?)(?:[.,;]| from | for | featuring |$)"
)


@dataclass
class ArtistSuggestion:
    artist: str
    source: str  # "YouTube" or "Wikipedia"


def suggest_artist(webpage_url: str, title: str) -> ArtistSuggestion | None:
    """Best-effort guess at the real artist for a track whose stored artist
    is wrong or missing (usually because it was filled from the YouTube
    uploader/channel name at download time). Tries two free signals in
    order: YouTube's own "<Artist> - Topic" auto-generated channel name
    (reliable when present), then a Wikipedia summary for the cleaned
    title ("... is a song by <Artist>")."""
    suggestion = _from_youtube_topic_channel(webpage_url)
    if suggestion:
        return suggestion
    return _from_wikipedia(title)


def _from_youtube_topic_channel(webpage_url: str) -> ArtistSuggestion | None:
    if not webpage_url:
        return None
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": False}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(webpage_url, download=False)
    except yt_dlp.utils.DownloadError:
        return None
    if not info:
        return None

    artist = info.get("artist")
    if artist:
        return ArtistSuggestion(artist=artist, source="YouTube")

    channel = info.get("channel") or ""
    if channel.endswith(" - Topic"):
        return ArtistSuggestion(artist=channel[: -len(" - Topic")].strip(), source="YouTube")
    return None


def _from_wikipedia(title: str) -> ArtistSuggestion | None:
    query = clean_title(title)
    if not query:
        return None

    search_params = {
        "action": "opensearch",
        "search": query,
        "limit": "1",
        "namespace": "0",
        "format": "json",
    }
    search_url = f"{WIKIPEDIA_SEARCH_URL}?{urllib.parse.urlencode(search_params)}"
    try:
        with urllib.request.urlopen(search_url, timeout=10) as resp:
            results = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError):
        return None

    pages = results[1] if len(results) > 1 else []
    if not pages:
        return None
    page_title = pages[0]

    summary_url = WIKIPEDIA_SUMMARY_URL.format(urllib.parse.quote(page_title.replace(" ", "_")))
    try:
        with urllib.request.urlopen(summary_url, timeout=10) as resp:
            summary = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError):
        return None

    match = _BY.search(summary.get("extract", ""))
    if not match:
        return None
    return ArtistSuggestion(artist=match.group(1).strip(), source="Wikipedia")
