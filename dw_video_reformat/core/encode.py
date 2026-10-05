"""ffmpeg re-encode backend for dw_video_reformat.

Summary:
    Builds and runs one ffmpeg command per source video, writing the result
    into an ``out_reformat`` subfolder of the dropped folder, mirroring the
    source hierarchy inside it. Progress is read
    from ffmpeg's ``-progress pipe:1`` stream and turned into a 0..1 fraction
    against the ffprobe duration.

Features:
    - EncodeSettings dataclass mirrors the UI param panel one-to-one.
    - build_command() is pure (no subprocess) so it can be inspected/tested.
    - run_encode() streams progress and honours a cancel callback.
    - No console window flashes on Windows.

Classes:
    EncodeSettings, Source, EncodeResult

Functions:
    is_video(path), collect_videos(paths), output_path(source, settings),
    normalize_frame_rate(value), frame_rate_label(rate),
    probe_duration(source), build_command(source, output, settings),
    run_encode(source, settings, on_progress, should_cancel)

Example:
    >>> settings = EncodeSettings(audio_enabled=False)
    >>> for source in collect_videos([pathlib.Path("shots/")]):
    ...     run_encode(source, settings)

Author: abaudoin
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import shutil
import subprocess
import sys
import typing

OUT_SUBFOLDER = "out_reformat"

VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv",
    ".mpg", ".mpeg", ".ts", ".mts", ".m2ts", ".mxf", ".3gp", ".ogv", ".gif",
}

# label -> ffmpeg encoder name
VIDEO_CODECS = {
    "H.264 (libx264)": "libx264",
    "H.265 / HEVC (libx265)": "libx265",
}
CONTAINERS = ["mp4", "mov", "mkv"]
PRESETS = [
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
]
PIXEL_FORMATS = ["yuv420p", "yuv422p", "yuv444p"]
# label -> ffmpeg -r value; "" keeps the source rate (and its variable timing).
# NTSC rates are exact fractions, a typed 29.97 would drift against 30000/1001.
FRAME_RATES = {
    "source": "",
    "23.976": "24000/1001",
    "24": "24",
    "25": "25",
    "29.97": "30000/1001",
    "30": "30",
    "50": "50",
    "60": "60",
    "100": "100",
    "120": "120",
}
AUDIO_CODECS = {
    "AAC": "aac",
    "MP3 (libmp3lame)": "libmp3lame",
}

# keys ffmpeg writes on the -progress stream; anything else is log text
_PROGRESS_KEYS = {
    "frame", "fps", "bitrate", "total_size", "out_time_us", "out_time_ms",
    "out_time", "dup_frames", "drop_frames", "speed", "progress",
}


@dataclasses.dataclass
class EncodeSettings:
    container: str = "mp4"
    video_codec: str = "libx264"
    crf: int = 18
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    max_width: int = 0        # 0 = keep source size
    fps: str = ""             # ffmpeg -r value ("30", "30000/1001"); "" = keep source rate
    audio_enabled: bool = True
    audio_codec: str = "aac"
    audio_bitrate: int = 192  # kbps
    faststart: bool = True
    overwrite: bool = True
    suffix: str = ""


@dataclasses.dataclass
class Source:
    """A queued video plus the folder it was dropped from.

    ``root`` is the dropped folder (or the file's own folder for a single
    file drop); the output tree mirrors ``path`` relative to it under
    ``<root>/out_reformat/``.
    """
    path: pathlib.Path
    root: pathlib.Path

    @property
    def relative(self) -> pathlib.Path:
        return self.path.relative_to(self.root)


@dataclasses.dataclass
class EncodeResult:
    source: Source
    output: pathlib.Path
    status: str          # "done" | "skipped" | "cancelled" | "failed"
    message: str = ""


def ffmpeg_path() -> typing.Optional[str]:
    """Locate ffmpeg: beside the frozen exe, then ``dw_video_reformat/bin/``, then PATH.

    The bundled lookup is what lets a colleague run the PyInstaller build with
    ``ffmpeg.exe`` dropped in the same folder and nothing installed.
    """
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    if getattr(sys, "frozen", False):
        candidates = [pathlib.Path(sys.executable).parent / exe]
    else:
        candidates = [pathlib.Path(__file__).resolve().parent.parent / "bin" / exe]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


def is_video(path: pathlib.Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTS


def collect_videos(paths: typing.Iterable[pathlib.Path]) -> list:
    """Expand a mix of files and folders (walked recursively) into Sources.

    A dropped folder becomes the root of every video found under it; a
    dropped file is rooted at its own folder. Any ``out_reformat`` folder is
    pruned from the walk, so dropping a folder twice does not queue its own
    results. Hidden folders (``.git``, ``.waveform_cache``...) are pruned too.
    """
    found = []
    for path in paths:
        path = pathlib.Path(path)
        if path.is_dir():
            for child in _walk_videos(path):
                found.append(Source(child, path))
        elif is_video(path):
            found.append(Source(path, path.parent))
    unique = []
    seen = set()
    for source in found:
        key = str(source.path.resolve()).lower()
        if key in seen or source.path.parent.name == OUT_SUBFOLDER:
            continue
        seen.add(key)
        unique.append(source)
    return unique


def _walk_videos(folder: pathlib.Path) -> list:
    found = []
    for child in sorted(folder.iterdir()):
        if child.is_dir():
            if child.name == OUT_SUBFOLDER or child.name.startswith("."):
                continue
            found.extend(_walk_videos(child))
        elif is_video(child):
            found.append(child)
    return found


def output_path(source: Source, settings: EncodeSettings) -> pathlib.Path:
    """``<root>/out_reformat/<relative folders>/<stem><suffix>.<container>``."""
    name = f"{source.path.stem}{settings.suffix}.{settings.container}"
    return source.root / OUT_SUBFOLDER / source.relative.parent / name


_RATE_RE = re.compile(r"^\d+(\.\d+)?(/\d+(\.\d+)?)?$")


def normalize_frame_rate(value) -> typing.Optional[str]:
    """Turn a label, number or ffmpeg rate into the ``-r`` value, or None if invalid.

    Accepts a FRAME_RATES label ("29.97"), a plain number ("48", 30.0, the
    float the old spinbox persisted) or a fraction ("30000/1001"). Empty,
    "source" and zero all mean keep the source rate and return "".
    """
    text = str(value).strip().lower()
    if text in ("", "source"):
        return ""
    if text in FRAME_RATES:
        return FRAME_RATES[text]
    if not _RATE_RE.match(text):
        return None
    numerator, _, denominator = text.partition("/")
    if denominator and float(denominator) == 0:
        return None
    if float(numerator) == 0:
        return ""
    if denominator:
        return text
    return f"{float(numerator):g}"


def frame_rate_label(rate: str) -> str:
    """Inverse of FRAME_RATES for display: "30000/1001" -> "29.97"."""
    for label, value in FRAME_RATES.items():
        if value == rate:
            return label
    return rate


def _popen_kwargs() -> dict:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe_duration(source: pathlib.Path) -> typing.Optional[float]:
    """Duration in seconds read off ffmpeg's own stream info, or None.

    ``ffmpeg -i file`` with no output exits non-zero but still prints the
    ``Duration: HH:MM:SS.ss`` line; using it avoids shipping ffprobe.
    """
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        return None
    cmd = [ffmpeg, "-hide_banner", "-i", str(source)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=30, **_popen_kwargs()
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _DURATION_RE.search(result.stderr)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    value = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return value if value > 0 else None


def build_command(
        source: pathlib.Path,
        output: pathlib.Path,
        settings: EncodeSettings) -> list:
    """Return the ffmpeg argv for one job. Pure: touches no file."""
    cmd = [
        ffmpeg_path() or "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error",
        "-progress", "pipe:1",
        "-y" if settings.overwrite else "-n",
        "-i", str(source),
        "-c:v", settings.video_codec,
        "-crf", str(settings.crf),
        "-preset", settings.preset,
        "-pix_fmt", settings.pixel_format,
    ]
    if settings.video_codec == "libx265":
        # hvc1 tag is what QuickTime / browsers expect for HEVC in mp4/mov
        cmd += ["-tag:v", "hvc1"]

    # yuv420p needs even dimensions; the scale filter enforces that either
    # way, with an optional width cap that never upscales
    if settings.max_width > 0:
        scale = f"scale=trunc(min({settings.max_width}\\,iw)/2)*2:-2"
    else:
        scale = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    cmd += ["-vf", scale]

    # an explicit output rate also forces constant frame rate, which is what
    # editors like Resolve want from YouTube's variable-rate sources
    if settings.fps:
        cmd += ["-r", settings.fps]

    if settings.audio_enabled:
        cmd += ["-c:a", settings.audio_codec, "-b:a", f"{settings.audio_bitrate}k"]
    else:
        cmd += ["-an"]

    if settings.faststart and settings.container in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]

    cmd.append(str(output))
    return cmd


def run_encode(
        source: Source,
        settings: EncodeSettings,
        on_progress: typing.Optional[typing.Callable[[float], None]] = None,
        should_cancel: typing.Optional[typing.Callable[[], bool]] = None) -> EncodeResult:
    """Encode one file, reporting a 0..1 fraction through ``on_progress``.

    The fraction is -1 when no duration could be probed (caller shows an
    indeterminate bar). A cancelled or failed job removes its partial output.
    """
    output = output_path(source, settings)
    if output.exists() and not settings.overwrite:
        return EncodeResult(source, output, "skipped", "output exists")
    output.parent.mkdir(parents=True, exist_ok=True)

    duration = probe_duration(source.path)
    cmd = build_command(source.path, output, settings)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_popen_kwargs(),
        )
    except FileNotFoundError:
        return EncodeResult(source, output, "failed", "ffmpeg not found on PATH")

    log_lines = []
    cancelled = False
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        key, sep, value = line.partition("=")
        if sep and key in _PROGRESS_KEYS:
            if key in ("out_time_us", "out_time_ms") and on_progress is not None:
                # both keys are microseconds (historical ffmpeg naming quirk)
                if duration:
                    try:
                        fraction = int(value) / 1_000_000 / duration
                    except ValueError:
                        continue
                    on_progress(max(0.0, min(fraction, 1.0)))
                else:
                    on_progress(-1.0)
        else:
            log_lines.append(line)
        if should_cancel is not None and should_cancel():
            cancelled = True
            proc.terminate()
            break
    proc.wait()

    if cancelled:
        _remove_quiet(output)
        return EncodeResult(source, output, "cancelled", "cancelled by user")
    if proc.returncode != 0 or not output.exists():
        _remove_quiet(output)
        message = "\n".join(log_lines[-10:]) or f"ffmpeg exit code {proc.returncode}"
        return EncodeResult(source, output, "failed", message)
    if on_progress is not None:
        on_progress(1.0)
    return EncodeResult(source, output, "done", "")


def _remove_quiet(path: pathlib.Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
