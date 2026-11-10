#!/usr/bin/env python3
"""Build the Windows application icon ``assets/weather.ico``.

Composes the sunny sprite over the classic Luna gradient and packs several
sizes into one multi-resolution ICO. Pillow is a build-time-only dependency;
the frozen application needs no image library because Tkinter reads GIFs
natively and Windows reads the ICO.

Run once to (re)create ``assets/weather.ico``::

    python tools/make_icon_ico.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
SKY_TOP = (214, 227, 247)  # #D6E3F7, the app background
SKY_BOTTOM = (140, 170, 214)


def build(dest: Path, source: Path) -> Path:
    from PIL import Image, ImageDraw

    sprite = Image.open(source).convert("RGBA")

    frames = []
    for size in ICON_SIZES:
        canvas = Image.new("RGBA", (size, size))
        draw = ImageDraw.Draw(canvas)
        for y in range(size):
            ratio = y / max(size - 1, 1)
            draw.line(
                [(0, y), (size, y)],
                fill=tuple(round(a + (b - a) * ratio) for a, b in zip(SKY_TOP, SKY_BOTTOM)),
            )
        inset = max(1, size // 8)
        art = sprite.resize((size - inset * 2, size - inset * 2), Image.NEAREST)
        canvas.alpha_composite(art, (inset, inset))
        frames.append(canvas)

    dest.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(dest, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    return dest


def main() -> int:
    source = ROOT / "icons" / "sunny.gif"
    dest = ROOT / "assets" / "weather.ico"
    if not source.exists():
        print(f"missing sprite: {source}; run tools/make_icons.py first", file=sys.stderr)
        return 1
    print(f"wrote {build(dest, source)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
