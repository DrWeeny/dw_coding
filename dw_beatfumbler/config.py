from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULTS = {
    "download_dir": "",
    "cookies_browser": "",  # empty = disabled; otherwise a yt-dlp browser key ("chrome", "firefox", "edge", "brave")
    "lastfm_api_key": "",  # empty = "Find Similar" disabled; free key at last.fm/api/account/create
}


@dataclass
class AppConfig:
    download_dir: str = DEFAULTS["download_dir"]
    cookies_browser: str = DEFAULTS["cookies_browser"]
    lastfm_api_key: str = DEFAULTS["lastfm_api_key"]

    @classmethod
    def load(cls) -> "AppConfig":
        if CONFIG_PATH.is_file():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            merged = dict(DEFAULTS)
            merged.update(data)
            return cls(**merged)
        return cls(**DEFAULTS)

    def save(self) -> None:
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
