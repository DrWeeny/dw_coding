from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image

_EXIF_IFD = 0x8769
_MAKE = 271
_MODEL = 272
_FOCAL_LENGTH = 37386
_LENS_MODEL = 42036

# Sony's internal model codes aren't the marketing name shown on the box.
# Extend as needed for other bodies.
CAMERA_FRIENDLY_NAMES = {
    "ILCE-7M3": "Sony a7 III",
}


def get_camera_line(photo_path: Path) -> Optional[str]:
    """Build a 'Shot on <camera> · <lens> at <focal>mm' line straight from
    EXIF, or None if the file is missing or has no usable EXIF. Deterministic
    (not an AI guess) since the data is right there in the file."""
    photo_path = Path(photo_path)
    if not photo_path.is_file():
        return None

    try:
        img = Image.open(photo_path)
        exif = img.getexif()
        if not exif:
            return None
        ifd0 = dict(exif)
        exif_ifd = exif.get_ifd(_EXIF_IFD)
    except Exception:
        return None

    make = ifd0.get(_MAKE, "")
    model = ifd0.get(_MODEL, "")
    lens = exif_ifd.get(_LENS_MODEL)
    focal = exif_ifd.get(_FOCAL_LENGTH)

    if not model:
        return None

    camera_name = CAMERA_FRIENDLY_NAMES.get(model.strip(), f"{make} {model}".strip())

    parts = [f"Shot on {camera_name}"]
    if lens:
        parts.append(lens)
    line = " · ".join(parts)
    if focal:
        line += f" at {int(round(focal))}mm"
    return line
