from __future__ import annotations

import re

# Any http(s) or bare www. token; not youtube-specific since yt-dlp supports
# hundreds of sites. Matches inside arbitrary text (e.g. a notepad list with
# links mixed among other lines/words), not just a whole-string paste.
_URL_RE = re.compile(r"(?:https?://|www\.)\S+")
_TRAILING_PUNCTUATION = ").,;:!?\"'"


def extract_links(text: str) -> list[str]:
    """Pull every URL out of arbitrary pasted/dropped text, de-duplicated
    and in the order first seen."""
    links: list[str] = []
    for match in _URL_RE.findall(text):
        link = match.rstrip(_TRAILING_PUNCTUATION)
        if link and link not in links:
            links.append(link)
    return links
