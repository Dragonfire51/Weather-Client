#!/usr/bin/env python3
"""Generate the retro pixel-art weather icon set (32x32 GIF, no dependencies).

Run once to (re)create ``icons/*.gif``::

    python tools/make_icons.py

The GIF encoder is intentionally self-contained so the repository needs no
image library at runtime or build time. Tkinter loads GIF natively.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from weather_icons import ICON_CATEGORIES

SIZE = 32

# Index 0 is reserved for transparency.
PALETTE: list[tuple[int, int, int]] = [
    (0, 0, 0),        # 0 transparent placeholder
    (0, 0, 0),        # 1 outline black
    (255, 255, 255),  # 2 cloud white
    (198, 212, 232),  # 3 cloud shadow
    (255, 210, 74),   # 4 sun yellow
    (242, 169, 59),   # 5 sun amber
    (59, 125, 216),   # 6 rain blue
    (31, 78, 156),    # 7 deep blue
    (138, 151, 166),  # 8 gray
    (255, 228, 92),   # 9 lightning
    (27, 42, 107),    # 10 night navy
    (231, 231, 231),  # 11 pale
    (120, 132, 150),  # 12 dark gray
    (255, 255, 255),  # 13 snow white
]

T = 0  # transparent
K, W, SH, Y, YD, B, DB, G, L, N, P, DG, SN = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13


class Canvas:
    def __init__(self, size: int = SIZE):
        self.size = size
        self.pixels = [[T] * size for _ in range(size)]

    def px(self, x: int, y: int, color: int) -> None:
        if 0 <= x < self.size and 0 <= y < self.size:
            self.pixels[y][x] = color

    def rect(self, x0: int, y0: int, x1: int, y1: int, color: int) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.px(x, y, color)

    def disc(self, cx: float, cy: float, r: float, color: int, fill: bool = True) -> None:
        for y in range(self.size):
            for x in range(self.size):
                dx, dy = x - cx + 0.5, y - cy + 0.5
                d = (dx * dx + dy * dy) ** 0.5
                inside = d <= r if fill else abs(d - r) <= 0.9
                if inside:
                    self.px(x, y, color)

    def ring(self, cx: float, cy: float, r: float, color: int) -> None:
        self.disc(cx, cy, r, color, fill=False)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: int, width: int = 1) -> None:
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(steps + 1):
            x = round(x0 + (x1 - x0) * i / steps)
            y = round(y0 + (y1 - y0) * i / steps)
            for oy in range(width):
                for ox in range(width):
                    self.px(x + ox, y + oy, color)

    def poly(self, points: list[tuple[int, int]], color: int) -> None:
        ys = [p[1] for p in points]
        for y in range(min(ys), max(ys) + 1):
            nodes: list[int] = []
            for i, (x0, y0) in enumerate(points):
                x1, y1 = points[(i + 1) % len(points)]
                if (y0 < y <= y1) or (y1 < y <= y0):
                    nodes.append(round(x0 + (y - y0) * (x1 - x0) / (y1 - y0)))
            nodes.sort()
            for j in range(0, len(nodes) - 1, 2):
                for x in range(nodes[j], nodes[j + 1] + 1):
                    self.px(x, y, color)

    def flatten(self) -> bytes:
        return bytes(c for row in self.pixels for c in row)


# --------------------------------------------------------------------------- #
# Drawing primitives shared by the sprites
# --------------------------------------------------------------------------- #
def draw_sun(c: Canvas, cx: float, cy: float, r: float = 6.0) -> None:
    import math

    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x0 = int(cx + math.cos(rad) * (r + 1))
        y0 = int(cy + math.sin(rad) * (r + 1))
        x1 = int(cx + math.cos(rad) * (r + 4))
        y1 = int(cy + math.sin(rad) * (r + 4))
        c.line(x0, y0, x1, y1, YD)
    c.disc(cx, cy, r, Y)
    c.disc(cx - 1.5, cy - 1.5, r * 0.5, YD)


def draw_cloud(c: Canvas, cx: float = 16.0, cy: float = 17.0, scale: float = 1.0) -> None:
    c.disc(cx - 6 * scale, cy, 5.2 * scale, W)
    c.disc(cx, cy - 4 * scale, 6.4 * scale, W)
    c.disc(cx + 6.5 * scale, cy - 0.5 * scale, 4.6 * scale, W)
    c.rect(int(cx - 10 * scale), int(cy), int(cx + 9 * scale), int(cy + 4 * scale), W)
    c.rect(int(cx - 10 * scale), int(cy + 3 * scale), int(cx + 9 * scale), int(cy + 4 * scale), SH)


def draw_rain(c: Canvas, offset: int = 0, count: int = 4, color: int = B) -> None:
    for i in range(count):
        x = 7 + i * 5 + offset
        c.line(x, 23, x - 2, 28, color)
        c.line(x + 1, 23, x - 1, 28, color)


def draw_snow(c: Canvas, offset: int = 0, count: int = 4) -> None:
    for i in range(count):
        x = 8 + i * 5 + offset
        y = 25 + (i % 2)
        c.px(x, y, SN)
        c.line(x - 1, y - 1, x + 1, y + 1, SN)
        c.line(x + 1, y - 1, x - 1, y + 1, SN)
        c.px(x, y - 2, SN)
        c.px(x, y + 2, SN)
        c.px(x - 2, y, SN)
        c.px(x + 2, y, SN)


def draw_bolt(c: Canvas) -> None:
    c.poly([(17, 20), (22, 20), (19, 25), (22, 25), (15, 31), (18, 26), (15, 26)], L)


def draw_stars(c: Canvas) -> None:
    for x, y in ((24, 7), (27, 12), (22, 15), (26, 20)):
        c.px(x, y, P)
        c.px(x - 1, y, P)
        c.px(x + 1, y, P)
        c.px(x, y - 1, P)
        c.px(x, y + 1, P)


# --------------------------------------------------------------------------- #
# Sprites
# --------------------------------------------------------------------------- #
def icon_sunny() -> Canvas:
    c = Canvas()
    draw_sun(c, 16, 16, 7)
    return c


def icon_mostly_sunny() -> Canvas:
    c = Canvas()
    draw_sun(c, 11, 11, 5.5)
    draw_cloud(c, 19, 20, 0.85)
    return c


def icon_partly_cloudy() -> Canvas:
    c = Canvas()
    draw_sun(c, 10, 10, 5)
    draw_cloud(c, 18, 19, 1.0)
    return c


def icon_cloudy() -> Canvas:
    c = Canvas()
    draw_cloud(c, 15, 20, 0.9)
    draw_cloud(c, 19, 14, 0.8)
    return c


def icon_rain() -> Canvas:
    c = Canvas()
    draw_cloud(c, 16, 15, 1.0)
    draw_rain(c)
    return c


def icon_showers() -> Canvas:
    c = Canvas()
    draw_sun(c, 22, 9, 4)
    draw_cloud(c, 15, 16, 0.95)
    draw_rain(c, count=3)
    return c


def icon_thunderstorm() -> Canvas:
    c = Canvas()
    draw_cloud(c, 16, 14, 1.0)
    draw_bolt(c)
    draw_rain(c, offset=12, count=1)
    return c


def icon_snow() -> Canvas:
    c = Canvas()
    draw_cloud(c, 16, 15, 1.0)
    draw_snow(c)
    return c


def icon_sleet() -> Canvas:
    c = Canvas()
    draw_cloud(c, 16, 15, 1.0)
    draw_rain(c, count=2)
    draw_snow(c, offset=10, count=2)
    return c


def icon_fog() -> Canvas:
    c = Canvas()
    draw_cloud(c, 16, 12, 0.9)
    for i, width in enumerate((16, 22, 18, 24)):
        y = 20 + i * 3
        x0 = 16 - width // 2
        c.rect(x0, y, x0 + width, y + 1, G if i % 2 else P)
    return c


def icon_windy() -> Canvas:
    c = Canvas()
    for i, (y, x0, x1) in enumerate(((10, 6, 21), (16, 4, 25), (22, 8, 23))):
        c.rect(x0, y, x1, y + 1, P)
        c.line(x1, y, x1 + 3, y - 3, P, width=2)
        c.px(x1 + 3, y - 3, P)
    return c


def icon_clear_night() -> Canvas:
    c = Canvas()
    c.disc(15, 16, 9, N)
    c.disc(10.5, 12.5, 7.5, T)
    draw_stars(c)
    return c


def icon_cloudy_night() -> Canvas:
    c = Canvas()
    c.disc(13, 12, 8, N)
    c.disc(9, 9, 6.5, T)
    draw_stars(c)
    draw_cloud(c, 18, 21, 0.85)
    return c


def icon_unknown() -> Canvas:
    c = Canvas()
    draw_cloud(c, 16, 15, 1.0)
    c.rect(14, 22, 17, 25, DB)
    c.px(15, 23, W)
    c.px(16, 23, W)
    c.rect(15, 27, 16, 28, DB)
    return c


SPRITES = {
    "sunny": icon_sunny,
    "mostly_sunny": icon_mostly_sunny,
    "partly_cloudy": icon_partly_cloudy,
    "cloudy": icon_cloudy,
    "rain": icon_rain,
    "showers": icon_showers,
    "thunderstorm": icon_thunderstorm,
    "snow": icon_snow,
    "sleet": icon_sleet,
    "fog": icon_fog,
    "windy": icon_windy,
    "clear_night": icon_clear_night,
    "cloudy_night": icon_cloudy_night,
    "unknown": icon_unknown,
}


# --------------------------------------------------------------------------- #
# Minimal GIF89a writer (LZW)
# --------------------------------------------------------------------------- #
class _BitWriter:
    def __init__(self) -> None:
        self.bytes = bytearray()
        self.acc = 0
        self.bits = 0

    def write(self, code: int, size: int) -> None:
        self.acc |= code << self.bits
        self.bits += size
        while self.bits >= 8:
            self.bytes.append(self.acc & 0xFF)
            self.acc >>= 8
            self.bits -= 8

    def flush(self) -> None:
        if self.bits:
            self.bytes.append(self.acc & 0xFF)
            self.acc = 0
            self.bits = 0


def lzw_encode(indices: bytes, min_code_size: int) -> bytes:
    clear = 1 << min_code_size
    end = clear + 1
    writer = _BitWriter()

    table: dict[bytes, int] = {bytes([i]): i for i in range(clear)}
    next_code = end + 1
    code_size = min_code_size + 1

    writer.write(clear, code_size)
    buffer = b""
    for value in indices:
        candidate = buffer + bytes([value])
        if candidate in table:
            buffer = candidate
            continue
        writer.write(table[buffer], code_size)
        table[candidate] = next_code
        next_code += 1
        if next_code > 4095:
            writer.write(clear, code_size)
            table = {bytes([i]): i for i in range(clear)}
            next_code = end + 1
            code_size = min_code_size + 1
        elif next_code > (1 << code_size) - 1:
            code_size += 1
        buffer = bytes([value])
    if buffer:
        writer.write(table[buffer], code_size)
    writer.write(end, code_size)
    writer.flush()
    return bytes(writer.bytes)


def write_gif(path: Path, indices: bytes, size: int = SIZE) -> None:
    color_table = bytearray()
    for r, g, b in PALETTE:
        color_table += bytes((r, g, b))
    # GIF color tables must be a power-of-two sized table (min 2 entries).
    table_bits = 4  # 16 colors
    table_size = 1 << table_bits
    while len(color_table) // 3 < table_size:
        color_table += b"\x00\x00\x00"

    out = bytearray(b"GIF89a")
    out += struct.pack("<HH", size, size)
    out += bytes([0xF0 | (table_bits - 1), 0, 0])  # global table, 8-bit color res
    out += bytes(color_table)
    # Netscape loop extension -> infinite animation (harmless for stills)
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    out += b"," + struct.pack("<HHHH", 0, 0, size, size) + b"\x00"
    out += bytes([8])  # LZW minimum code size
    compressed = lzw_encode(indices, 8)
    for i in range(0, len(compressed), 255):
        chunk = compressed[i : i + 255]
        out += bytes([len(chunk)]) + chunk
    out += b"\x00\x3b"  # block terminator + trailer
    path.write_bytes(bytes(out))


def main() -> int:
    out_dir = ROOT / "icons"
    out_dir.mkdir(exist_ok=True)
    for name in ICON_CATEGORIES:
        sprite = SPRITES.get(name, icon_unknown)
        canvas = sprite()
        write_gif(out_dir / f"{name}.gif", canvas.flatten())
        print(f"wrote icons/{name}.gif")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
