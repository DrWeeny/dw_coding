from __future__ import annotations

import subprocess
from pathlib import Path


class ConvertError(Exception):
    pass


def convert_to_mp3(path: Path, quality: str = "192") -> Path:
    """Re-encode an existing local audio file to MP3 via ffmpeg — no
    re-download needed, and it still works if the source video has since
    gone private or been removed. Deletes the original file on success."""
    out_path = path.with_suffix(".mp3")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-codec:a", "libmp3lame", "-b:a", f"{quality}k", str(out_path)],
            capture_output=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise ConvertError("ffmpeg not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConvertError("ffmpeg conversion timed out") from exc

    if result.returncode != 0 or not out_path.exists():
        raise ConvertError(result.stderr.decode(errors="replace"))

    path.unlink()
    return out_path
