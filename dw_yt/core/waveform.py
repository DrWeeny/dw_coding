from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).resolve().parent.parent / ".waveform_cache"


def waveform_path_for(audio_path: Path) -> Path:
    return CACHE_DIR / f"{audio_path.stem}.png"


def ensure_waveform_image(audio_path: Path, width: int = 900, height: int = 90) -> Optional[Path]:
    """Generate (and cache) a waveform PNG for audio_path via ffmpeg.
    Returns the image path, or None if ffmpeg is missing or generation fails
    — callers should degrade gracefully (seeking still works without one)."""
    out_path = waveform_path_for(audio_path)
    if out_path.exists():
        return out_path

    CACHE_DIR.mkdir(exist_ok=True)
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_path),
                "-filter_complex",
                f"showwavespic=s={width}x{height}:colors=0x5b9bd5",
                "-frames:v",
                "1",
                str(out_path),
            ],
            capture_output=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    return out_path if result.returncode == 0 and out_path.exists() else None
