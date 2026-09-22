"""Freeze dw_video_reformat into a self-contained folder for colleagues without Python.

Summary:
    Runs PyInstaller (one-folder, windowed) on ``app.py``, drops ``ffmpeg.exe``
    beside the produced exe and zips the folder. The recipient unzips it
    anywhere and makes a desktop shortcut to ``dw_video_reformat.exe``.

Usage (from the repo ``.venv``, which has PySide6 + pyinstaller)::

    .venv\\Scripts\\python.exe dw_video_reformat\\build_exe.py
    .venv\\Scripts\\python.exe dw_video_reformat\\build_exe.py --ffmpeg D:\\tools\\ffmpeg.exe
    .venv\\Scripts\\python.exe dw_video_reformat\\build_exe.py --no-zip

``--ffmpeg`` defaults to the ffmpeg found by ``core.encode.ffmpeg_path()``
(PATH). A "full" gyan.dev build is ~220 MB; the "essentials" build (~90 MB)
has everything this tool uses (libx264, libx265, aac) and makes a much
smaller zip.

Outputs land in ``dw_video_reformat/dist/``: ``dw_video_reformat/`` (the folder to ship)
and ``dw_reformat_<date>.zip``. ``build/`` and ``dist/`` are scratch.

Author: abaudoin
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import encode  # noqa: E402

APP_NAME = "dw_video_reformat"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ffmpeg", help="ffmpeg.exe to bundle (default: the one on PATH)")
    parser.add_argument("--no-zip", action="store_true", help="skip the zip step")
    args = parser.parse_args()

    ffmpeg = args.ffmpeg or encode.ffmpeg_path()
    if ffmpeg is None or not pathlib.Path(ffmpeg).is_file():
        print("ffmpeg.exe not found - pass --ffmpeg <path>")
        return 1

    dist = HERE / "dist"
    build = HERE / "build"
    shutil.rmtree(dist / APP_NAME, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name", APP_NAME,
        "--distpath", str(dist),
        "--workpath", str(build),
        "--specpath", str(build),
        "--paths", str(HERE),
        # only the Qt modules the app imports; keeps the folder small
        "--exclude-module", "PySide6.QtNetwork",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtOpenGL",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "PySide6.QtSvg",
        str(HERE / "app.py"),
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return result.returncode

    out_dir = dist / APP_NAME
    shutil.copy2(ffmpeg, out_dir / "ffmpeg.exe")
    (out_dir / "README.txt").write_text(
        "dw_video_reformat - drop videos or folders, get h264 mp4 files in an out_reformat subfolder.\n"
        "\n"
        "1. Keep this folder together (the exe needs the _internal folder and ffmpeg.exe beside it).\n"
        "2. Right-click dw_video_reformat.exe > Send to > Desktop (create shortcut).\n"
        "3. Drop videos on the window, adjust the parameters on the right, press Start.\n",
        encoding="utf-8",
    )
    print(f"built: {out_dir}")

    if not args.no_zip:
        stamp = datetime.date.today().strftime("%Y%m%d")
        archive = shutil.make_archive(str(dist / f"{APP_NAME}_{stamp}"), "zip", dist, APP_NAME)
        size_mb = pathlib.Path(archive).stat().st_size / (1024 * 1024)
        print(f"zipped: {archive} ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
