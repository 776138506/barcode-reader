"""从 SVG 矢量源生成应用图标（icon.png / icon.ico / icon.icns）。

用法: .venv/bin/python tools/gen_icon.py
输出: 项目根目录 icon.svg（源）+ icon.png + icon.ico + icon.icns（仅 macOS）
依赖: PySide6（QSvgRenderer 渲染）、zxing-cpp（真 Code128 条宽）、Pillow、numpy
"""
import io
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import zxingcpp
from PIL import Image, ImageDraw
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
S = 1024  # 设计稿尺寸（SVG viewBox）

BG = "#29364C"      # 深蓝底
CARD = "#FAFBFD"    # 白卡
GREEN_TOP = "#3EE6A8"
GREEN_BOT = "#22B573"


def barcode_runs() -> list[int]:
    """真 Code128 的条宽序列（模块单位）。"""
    arr = np.array(zxingcpp.create_barcode("BCR-2024", zxingcpp.BarcodeFormat.Code128)
                   .to_image(scale=1, add_quiet_zones=False))
    row = arr[0]
    runs, cur = [], 0
    for v in row:
        if v < 128:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return runs


def build_svg() -> str:
    card = (170, 296, 684, 432)  # x, y, w, h
    t, L = 46, 175               # 绿角线宽/臂长
    corners = [(170, 296, 1, 1), (854, 296, -1, 1), (170, 728, 1, -1), (854, 728, -1, -1)]
    paths = []
    for cx, cy, sx, sy in corners:
        # 单条路径画 L：圆帽 + 圆接头，无拼接凸起
        d = f"M {cx + sx*L} {cy} L {cx} {cy} L {cx} {cy + sy*L}"
        paths.append(
            f'<path d="{d}" fill="none" stroke="url(#green)" stroke-width="{t}"'
            f' stroke-linecap="round" stroke-linejoin="round" filter="url(#cshadow)"/>')

    # 条码：按真条宽铺满卡内区域（x 260..764, y 377..647）
    runs = barcode_runs()
    total = sum(runs) + (len(runs) - 1)  # 条间距 = 1 模块
    unit = 504 / total
    x, rects = 260.0, []
    for w in runs:
        rects.append(f'<rect x="{x:.2f}" y="377" width="{w*unit:.2f}" height="270" fill="#0F172A"/>')
        x += (w + 1) * unit

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}">
  <defs>
    <linearGradient id="green" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{GREEN_TOP}"/>
      <stop offset="1" stop-color="{GREEN_BOT}"/>
    </linearGradient>
    <filter id="cardshadow" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="8" dy="14" stdDeviation="12" flood-color="#080C16" flood-opacity="0.55"/>
    </filter>
    <filter id="cshadow" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="4" dy="8" stdDeviation="6" flood-color="#080C16" flood-opacity="0.45"/>
    </filter>
  </defs>
  <rect x="32" y="32" width="960" height="960" rx="230" fill="{BG}"/>
  <rect x="{card[0]}" y="{card[1]}" width="{card[2]}" height="{card[3]}" rx="48"
        fill="{CARD}" filter="url(#cardshadow)"/>
  {''.join(rects)}
  {''.join(paths)}
</svg>'''


def render(svg: str, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(QByteArray(svg.encode()))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def qimage_to_pil(img: QImage) -> Image.Image:
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (img.width(), img.height()), bytes(img.constBits()))


def draw_small(S: int) -> Image.Image:
    """小尺寸简化版（少粗条大角，保证 16px 可辨）——与矢量版风格一致。"""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, S // 32)
    d.rounded_rectangle((pad, pad, S - pad, S - pad), radius=S // 5, fill=BG)
    m = S // 5
    d.rounded_rectangle((m, S * 7 // 20, S - m, S * 13 // 20), radius=max(1, S // 16), fill=CARD)
    bw = max(1, S // 16)
    x = m + S // 10
    for _ in range(5):
        d.rectangle((x, S * 9 // 28, x + bw, S * 19 // 28), fill="#0F172A")
        x += bw * 2
    G, t, L, c = "#2FD89A", max(1, S // 12), S // 4, S // 10
    for cx, cy, sx, sy in ((c, c, 1, 1), (S - c, c, -1, 1), (c, S - c, 1, -1), (S - c, S - c, -1, -1)):
        d.line((cx, cy, cx + sx * L, cy), fill=G, width=t)
        d.line((cx, cy, cx, cy + sy * L), fill=G, width=t)
        d.ellipse((cx - t // 2, cy - t // 2, cx + t // 2, cy + t // 2), fill=G)
    return img


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841
    svg = build_svg()
    (ROOT / "icon.svg").write_text(svg, encoding="utf-8")

    # 4x 超采样渲染再降采样，边缘零锯齿
    big = qimage_to_pil(render(svg, 4096)).resize((S, S), Image.LANCZOS)
    big.save(ROOT / "icon.png")

    frames = {}
    for s in (16, 24, 32):
        frames[s] = draw_small(64).resize((s, s), Image.LANCZOS)
    for s in (48, 64, 128, 256):
        frames[s] = big.resize((s, s), Image.LANCZOS)
    blobs = {}
    for s, im in frames.items():
        buf = io.BytesIO()
        im.save(buf, "PNG")
        blobs[s] = buf.getvalue()
    header = struct.pack("<HHH", 0, 1, len(blobs))
    entries, offset = b"", 6 + 16 * len(blobs)
    data = b""
    for s in sorted(blobs):
        blob = blobs[s]
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    (ROOT / "icon.ico").write_bytes(header + entries + data)

    if sys.platform == "darwin":
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            iset = Path(td) / "icon.iconset"
            iset.mkdir()
            for s in (16, 32, 128, 256, 512):
                big.resize((s, s), Image.LANCZOS).save(iset / f"icon_{s}x{s}.png")
                big.resize((s * 2, s * 2), Image.LANCZOS).save(iset / f"icon_{s}x{s}@2x.png")
            subprocess.run(["iconutil", "-c", "icns", "-o", str(ROOT / "icon.icns"), str(iset)],
                           check=True)
    print("icon.svg / icon.png / icon.ico" + (" / icon.icns" if sys.platform == "darwin" else "") + " 已生成")


if __name__ == "__main__":
    main()
