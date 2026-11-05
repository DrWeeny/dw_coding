from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime
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
        """A damaged config.json must not stop the app. It's moved aside
        rather than overwritten since it holds things like the webhook URL,
        and the app then asks for the root folder again."""
        merged = dict(DEFAULTS)
        if CONFIG_PATH.is_file():
            try:
                merged.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
            except (ValueError, TypeError) as exc:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                aside = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.corrupt-{stamp}")
                os.replace(CONFIG_PATH, aside)
                print(f"dw_insta: {CONFIG_PATH.name} could not be read ({exc}), kept as {aside.name}")
        names = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in merged.items() if key in names})

    def save(self) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=str(CONFIG_PATH.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, CONFIG_PATH)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
