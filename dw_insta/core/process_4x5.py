from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image

from .scanner import IMAGE_EXTS

# Instagram crops anything outside these feed limits, so a photo is padded to
# the nearest limit instead. All integer maths: rounding down would leave the
# result a pixel past the limit, which is exactly what gets cropped.
PORTRAIT_LIMIT = (4, 5)  # width, height: the tallest feed frame
LANDSCAPE_LIMIT = (191, 100)  # width, height: the widest feed frame
PAD_COLOR = (255, 255, 255)
JPEG_EXTS = (".jpg", ".jpeg")


def fit_canvas(width: int, height: int) -> tuple[int, int]:
    """Smallest canvas holding the whole photo inside Instagram's limits.
    Only ever grows, so nothing is cropped."""
    wide, tall = PORTRAIT_LIMIT
    if width * tall < height * wide:
        return -(-height * wide // tall), height
    wide, tall = LANDSCAPE_LIMIT
    if width * tall > height * wide:
        return width, -(-width * tall // wide)
    return width, height


def _is_current(source: Path, out_path: Path) -> bool:
    """An existing output is kept unless the photo was re-exported since, or
    it would get cropped by Instagram (e.g. built with the old 4:5.95 ratio).
    A hand-made crop that fits the limits is left alone."""
    if not out_path.is_file():
        return False
    if source.stat().st_mtime_ns > out_path.stat().st_mtime_ns:
        return False
    try:
        with Image.open(out_path) as existing:
            size = existing.size
    except Exception:
        return False
    return fit_canvas(*size) == size


def _build(source: Path, out_path: Path) -> str:
    """Write one output and return its report key. Goes through a temp file so
    a failure can't leave a half-written photo in out_4x5/."""
    tmp_path = out_path.with_name(f".{out_path.stem}.building{out_path.suffix}")
    try:
        with Image.open(source) as img:
            img.load()  # a half-exported file only fails once it's decoded
            width, height = img.size
            canvas_size = fit_canvas(width, height)

            if canvas_size == (width, height):
                # Nothing to change, so keep the export's exact bytes rather
                # than re-encoding it.
                shutil.copy2(source, tmp_path)
                key = "landscape" if width >= height else "copied"
            else:
                save_kwargs = {key: img.info[key] for key in ("exif", "icc_profile") if img.info.get(key)}
                if source.suffix.lower() in JPEG_EXTS:
                    save_kwargs.update(quality=95, subsampling=0)
                image_format = img.format
                photo = img if img.mode in ("RGB", "RGBA") else img.convert("RGB")
                canvas = Image.new(photo.mode, canvas_size, PAD_COLOR)
                canvas.paste(photo, ((canvas_size[0] - width) // 2, (canvas_size[1] - height) // 2))
                canvas.save(tmp_path, format=image_format, **save_kwargs)
                key = "padded"
        os.replace(tmp_path, out_path)
        return key
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def process_series(source_dir: Path) -> dict[str, list[str]]:
    """Fill <series>/out_4x5/ from the photos sitting in <series>/. EXIF and
    ICC are preserved so the gear line still reads off the processed file. Up
    to date outputs are left alone, so this stays cheap to call on every
    refresh. An unreadable photo, such as one Lightroom is still exporting, is
    reported and picked up by a later refresh instead of stopping the rest.

    Returns {"padded": [...], "copied": [...], "landscape": [...],
    "replaced": [...], "failed": ["name: reason", ...]}. "replaced" also
    appears in one of the first three."""
    source_dir = Path(source_dir)
    out_dir = source_dir / "out_4x5"
    report: dict[str, list[str]] = {"padded": [], "copied": [], "landscape": [], "replaced": [], "failed": []}

    for entry in sorted(source_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in IMAGE_EXTS:
            continue
        out_path = out_dir / entry.name
        if _is_current(entry, out_path):
            continue
        existed = out_path.is_file()
        try:
            out_dir.mkdir(exist_ok=True)
            report[_build(entry, out_path)].append(entry.name)
        except Exception as exc:
            report["failed"].append(f"{entry.name}: {exc}")
            continue
        if existed:
            report["replaced"].append(entry.name)

    return report
