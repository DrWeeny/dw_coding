from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

INSTAGRAM_BASE_URL = "https://www.instagram.com/"

DEFAULTS = {
    "root_dir": "",
    "active_series": None,
    "instagram_profile_url": INSTAGRAM_BASE_URL,
    "discord_webhook_url": None,
}


@dataclass
class AppConfig:
    root_dir: str
    active_series: Optional[str] = None
    instagram_profile_url: str = DEFAULTS["instagram_profile_url"]
    discord_webhook_url: Optional[str] = None

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
