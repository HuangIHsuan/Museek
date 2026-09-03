"""產生 PWA 圖示（不依賴 Pillow）。品牌標記＝等化器色條，配色取自前端 CSS 變數。

用法：python scripts/generate_icons.py
"""
from __future__ import annotations

import os
import struct
import zlib

INK = (0x14, 0x14, 0x0F)
LIME = (0xB6, 0xF4, 0x14)
ACCENT = (0xE8, 0x00, 0x9C)
PAPER = (0xF2, 0xF1, 0xEC)

# 四根色條的（顏色, 高度比例）
BARS = [(LIME, 0.55), (PAPER, 0.80), (ACCENT, 0.38), (LIME, 0.66)]


def render(size: int, background=INK, padding_ratio: float = 0.22) -> bytes:
    pad = int(size * padding_ratio)
    inner = size - pad * 2
    gap = max(2, inner // 18)
    bar_width = (inner - gap * (len(BARS) - 1)) // len(BARS)

    rows = [[background] * size for _ in range(size)]
    for index, (color, ratio) in enumerate(BARS):
        left = pad + index * (bar_width + gap)
        height = int(inner * ratio)
        top = pad + inner - height
        for y in range(top, top + height):
            for x in range(left, left + bar_width):
                rows[y][x] = color

    raw = b"".join(b"\x00" + bytes(v for pixel in row for v in pixel) for row in rows)
    return _png(size, size, raw)


def _png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolor
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def main() -> None:
    out = os.path.join("app", "static", "icons")
    os.makedirs(out, exist_ok=True)
    targets = [("icon-192.png", 192, INK), ("icon-512.png", 512, INK),
               ("icon-maskable-512.png", 512, INK),
               # iOS 會把 apple-touch-icon 直接貼在主畫面，不做圓角以外的處理
               ("apple-touch-icon.png", 180, INK)]
    for name, size, background in targets:
        path = os.path.join(out, name)
        padding = 0.28 if "maskable" in name else 0.22
        with open(path, "wb") as handle:
            handle.write(render(size, background, padding))
        print("寫入", path)


if __name__ == "__main__":
    main()
