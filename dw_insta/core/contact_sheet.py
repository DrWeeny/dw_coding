from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TILE_WIDTH = 220
GAP = 6
LABEL_HEIGHT = 22
BG_COLOR = (24, 24, 24)
LABEL_BG = (0, 0, 0)
LABEL_FG = (255, 255, 255)


def build_contact_sheet(
    photos: list[tuple[str, Path]],
    out_path: Path,
    columns: int = 5,
    tile_width: int = TILE_WIDTH,
) -> Path:
    """Lay out (label, image_path) pairs in a labeled grid so many photos
    can be reviewed in a single image read instead of one read per photo.
    Keeps suggestion passes cheap in tool calls and vision tokens."""
    if not photos:
        raise ValueError("no photos to lay out")

    thumbs: list[tuple[str, Image.Image]] = []
    max_tile_h = 0
    for label, path in photos:
        img = Image.open(path).convert("RGB")
        ratio = tile_width / img.width
        tile_h = int(img.height * ratio)
        img = img.resize((tile_width, tile_h), Image.LANCZOS)
        thumbs.append((label, img))
        max_tile_h = max(max_tile_h, tile_h)

    rows = -(-len(thumbs) // columns)
    cell_w = tile_width + GAP
    cell_h = max_tile_h + LABEL_HEIGHT + GAP

    sheet = Image.new("RGB", (columns * cell_w + GAP, rows * cell_h + GAP), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()

    for i, (label, img) in enumerate(thumbs):
        col = i % columns
        row = i // columns
        x = GAP + col * cell_w
        y = GAP + row * cell_h
        sheet.paste(img, (x, y))
        draw.rectangle(
            [x, y + img.height, x + tile_width, y + img.height + LABEL_HEIGHT],
            fill=LABEL_BG,
        )
        draw.text((x + 4, y + img.height + 3), label, fill=LABEL_FG, font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=85)
    return out_path
