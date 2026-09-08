"""產生 PWA 圖示（不依賴 Pillow）。品牌標記＝等化器色條，配色取自前端 CSS 變數。

圖案跟 index.html 裡那個 .mark 是同一份：24×24 的點陣格，色條寬 2、間隔 2、
左右各留 3，每根切成 3 高、間隔 1 的方塊。放大一律用整數倍最近鄰，
方塊邊才不會被內插糊掉——這是點陣圖示唯一能放大的方式。

外框的缺角只做在網頁上那個 .mark：PNG 這裡沒有 alpha 通道，各平台又會自己
套遮罩與圓角，硬把角挖掉反而會露出黑邊。

用法：python scripts/generate_icons.py
"""
from __future__ import annotations

import os
import struct
import zlib

INK = (0x14, 0x14, 0x0F)
LIME = (0xB6, 0xF4, 0x14)
ACCENT = (0xE8, 0x00, 0x9C)

GRID = 24
BLOCK_H = 3          # 一個方塊 3 格高
BLOCK_GAP = 1        # 方塊之間留 1 格
BASELINE = 20        # 所有色條都畫到這一列為止（上留 5、下留 4，重心才在中間）

# （x、最上面那個方塊的 y、顏色）——高低是對稱的：高、中、低、中、高
BARS = [(3, 5, ACCENT), (7, 9, LIME), (11, 13, LIME), (15, 9, LIME), (19, 5, ACCENT)]


def logo_grid() -> list[list[tuple[int, int, int]]]:
    """畫出 24×24 的點陣圖案，回傳一格一個顏色。"""
    cells = [[INK] * GRID for _ in range(GRID)]
    for left, top, color in BARS:
        for y in range(top, BASELINE, BLOCK_H + BLOCK_GAP):
            for row in range(y, y + BLOCK_H):
                for x in range(left, left + 2):
                    cells[row][x] = color
    return cells


def render(size: int, fill_ratio: float = 0.88) -> bytes:
    """把點陣圖案用整數倍放大後置中；周圍補底色。"""
    cells = logo_grid()
    scale = max(1, int(size * fill_ratio) // GRID)
    drawn = scale * GRID
    offset = (size - drawn) // 2

    rows = [[INK] * size for _ in range(size)]
    for y in range(drawn):
        row = rows[offset + y]
        source = cells[y // scale]
        for x in range(drawn):
            row[offset + x] = source[x // scale]

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
    targets = [("icon-192.png", 192, 0.88), ("icon-512.png", 512, 0.88),
               # maskable 的安全區只有中間那圈，圖案要縮小一點才不會被裁到
               ("icon-maskable-512.png", 512, 0.66),
               # iOS 會把 apple-touch-icon 直接貼在主畫面，不做圓角以外的處理
               ("apple-touch-icon.png", 180, 0.80)]
    for name, size, fill_ratio in targets:
        path = os.path.join(out, name)
        with open(path, "wb") as handle:
            handle.write(render(size, fill_ratio))
        print("寫入", path)


if __name__ == "__main__":
    main()
