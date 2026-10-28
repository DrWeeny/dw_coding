from __future__ import annotations

from pathlib import Path

from PIL import Image

from .scanner import IMAGE_EXTS

# Instagram's tallest portrait frame is 4:5; the extra .95 leaves a small
# margin so nothing gets clipped by the feed's own crop. Same value as the
# original dw_krita/resize_4x5_headless.py script this replaces.
ASPECT_DIVISOR = 5.95
PAD_COLOR = (255, 255, 255)


def target_width(width: int, height: int) -> int:
    return int(height * 4 / ASPECT_DIVISOR)


def process_series(source_dir: Path) -> dict[str, list[str]]:
    """Fill <series>/out_4x5/ from the photos sitting in <series>/. A
    portrait photo narrower than 4:5.95 has its canvas extended (white,
    centred) to that width, as the old Krita batch did. Everything else -
    wider portraits, square and landscape photos - is copied as it is: a
    16:9 landscape already fits Instagram's 1.91:1 limit, and the batch's
    "skip landscape for now" rule only ever meant the photos had to be
    copied by hand. EXIF and ICC are preserved so the gear line still reads
    off the processed file. Photos already present in out_4x5/ are left
    alone so this stays cheap to call on every refresh.

    Returns {"padded": [...], "copied": [...], "landscape": [...]}."""
    source_dir = Path(source_dir)
    out_dir = source_dir / "out_4x5"
    report: dict[str, list[str]] = {"padded": [], "copied": [], "landscape": []}

    for entry in sorted(source_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in IMAGE_EXTS:
            continue
        out_path = out_dir / entry.name
        if out_path.is_file():
            continue

        img = Image.open(entry)
        width, height = img.size
        out_dir.mkdir(exist_ok=True)
        save_kwargs = {}
        for key in ("exif", "icc_profile"):
            if img.info.get(key):
                save_kwargs[key] = img.info[key]
        if entry.suffix.lower() in (".jpg", ".jpeg"):
            save_kwargs["quality"] = 95
            save_kwargs["subsampling"] = 0

        new_width = target_width(width, height)
        if width >= height:
            img.save(out_path, **save_kwargs)
            report["landscape"].append(entry.name)
        elif width < new_width:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            canvas = Image.new(img.mode, (new_width, height), PAD_COLOR)
            canvas.paste(img, ((new_width - width) // 2, 0))
            canvas.save(out_path, **save_kwargs)
            report["padded"].append(entry.name)
        else:
            img.save(out_path, **save_kwargs)
            report["copied"].append(entry.name)

    return report
