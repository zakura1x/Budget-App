"""
Draw the app icons (UX-09) into app/web/static/icons/ - run on YOUR machine;
the PNGs are committed, like the bundle.

    python scripts/generate_icons.py

An indigo tile (the theme.css accent) with the Home ring on it: the one image the app is about. Pillow
is used here only; the server never needs it.

    icon-192.png, icon-512.png   rounded tile, transparent corners
    maskable-512.png             full bleed, the mark inside the 80% safe zone
    apple-touch-icon.png         180x180, full bleed - iOS rounds it itself
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

ACCENT = (79, 84, 170, 255)
RING_TRACK = (255, 255, 255, 90)
WHITE = (255, 255, 255, 255)
SCALE = 4  # draw large, shrink down - smooth edges without an antialiasing library


def draw(size: int, *, rounded: bool, mark: float):
    from PIL import Image, ImageDraw

    big = size * SCALE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    if rounded:
        pen.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=ACCENT)
    else:
        pen.rectangle((0, 0, big, big), fill=ACCENT)

    diameter = big * mark
    left = (big - diameter) / 2
    box = (left, left, left + diameter, left + diameter)
    width = int(diameter * 0.13)
    pen.arc(box, 0, 360, fill=RING_TRACK, width=width)
    pen.arc(box, -90, 180, fill=WHITE, width=width)  # three quarters of the budget used, calmly
    dot = diameter * 0.12
    centre = big / 2
    pen.ellipse((centre - dot / 2, centre - dot / 2, centre + dot / 2, centre + dot / 2), fill=WHITE)
    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    target = ROOT / "app" / "web" / "static" / "icons"
    target.mkdir(parents=True, exist_ok=True)
    draw(192, rounded=True, mark=0.56).save(target / "icon-192.png")
    draw(512, rounded=True, mark=0.56).save(target / "icon-512.png")
    draw(512, rounded=False, mark=0.46).save(target / "maskable-512.png")
    draw(180, rounded=False, mark=0.52).convert("RGB").save(target / "apple-touch-icon.png")
    for path in sorted(target.glob("*.png")):
        print(path.relative_to(ROOT), path.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
