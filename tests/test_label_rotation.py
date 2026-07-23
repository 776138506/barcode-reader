"""标签方向增强测试：角度归一化、锚点避让、旋转像素、水平回归（D29）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import zxingcpp  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from decoder import decode_image  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui.preview_window import (Frame, build_frames, frame_angle,  # noqa: E402
                               rotated_label_anchor)

IMG_DIR = Path(__file__).resolve().parent / "images"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([]) 
    yield app


def _make_window(tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    return mw.MainWindow(settings=settings, history_db=tmp_path / "h.db",
                         profile_store=ProfileStore(tmp_path / "p.json"),
                         template_store=TemplateStore(tmp_path / "t.json"))


def _quad(tl, tr, br, bl):
    return Frame(points=[tl, tr, br, bl], seq=1, suspect=False, content="X")


# ---------- 角度归一化 ----------

def test_frame_angle_normalization():
    assert frame_angle(_quad((50, 30), (383, 30), (383, 129), (50, 129))) == 0.0
    # 90°（TL→TR 向下）
    assert frame_angle(_quad((129, 50), (129, 383), (30, 383), (30, 50))) == 90.0
    # 270°（TL→TR 向上）→ 归一化为 +90（文字不倒置）
    assert frame_angle(_quad((129, 383), (129, 50), (30, 50), (30, 383))) == 90.0
    # 180°（TL→TR 向左）→ 归一化为 0
    assert frame_angle(_quad((383, 30), (50, 30), (50, 129), (383, 129))) == 0.0
    # 非 90 倍数
    assert frame_angle(_quad((0, 0), (100, 26.8), (90, 50), (-10, 23.2))) == pytest.approx(15.0, abs=0.5)
    assert frame_angle(_quad((0, 0), (100, -26.8), (110, -3.2), (10, 23.6))) == pytest.approx(-15.0, abs=0.5)
    # 135° → -45°
    assert frame_angle(_quad((0, 0), (70.7, -70.7), (100, -41.4), (29.3, 29.3))) == pytest.approx(-45.0, abs=0.5)


# ---------- 锚点与避让 ----------

def test_anchor_outside_box_vertical():
    """竖码：标签锚点在框外侧（左右一侧），不在框内。"""
    frame = _quad((129, 50), (129, 383), (30, 383), (30, 50))
    ax, ay, ang = rotated_label_anchor(frame, 90.0, 60, 14, 400, 762)
    assert ang == 90.0
    assert ax < 30 or ax > 129, f"锚点未避开框体: ({ax},{ay})"


def test_anchor_flips_when_out_of_bounds():
    """标签出图片边界时翻到另一侧（竖码左侧出界 → 翻到右侧）。"""
    # 框中心在 TL 右侧 → 首选向左偏移，x=10-16=-6 出界 → 翻到右侧 x=26
    frame = _quad((10, 50), (10, 383), (35, 383), (35, 50))
    ax, ay, _ = rotated_label_anchor(frame, 90.0, 60, 14, 400, 762)
    assert ax == 10 + 16, f"未翻转到右侧: {ax}"
    assert ax >= 0 and ay >= 0

    # 右侧竖码（标签向下延伸）在界内时不翻转
    frame2 = _quad((350, 50), (350, 383), (320, 383), (320, 50))
    ax2, _, _ = rotated_label_anchor(frame2, 90.0, 60, 14, 400, 762)
    assert ax2 > 350, "界内不应翻转"


def test_anchor_real_corner_convention():
    """实证角点约定：旋转 90° 的 Code128，zxing TL→TR 沿阅读方向（向下）。"""
    sys.path.insert(0, str(IMG_DIR.parent))
    from gen_test_images import make_barcode, pad
    img = pad(make_barcode("ROT-TEST-123", "Code128", 480, 150), 30)
    rotated = img.rotate(-90, expand=True, fillcolor=255)
    results = [b for b in zxingcpp.read_barcodes(rotated.convert("RGB")) if b.valid]
    assert results
    p = results[0].position
    tl, tr = (p.top_left.x, p.top_left.y), (p.top_right.x, p.top_right.y)
    assert abs(tr[0] - tl[0]) < abs(tr[1] - tl[1]), "TL→TR 应沿竖直方向"
    assert tr[1] > tl[1], "TL→TR 应向下（阅读方向）"


# ---------- 像素级：90° 旋转码标签竖排分布 ----------

def test_vertical_code_label_is_vertical(qapp, tmp_path):
    """90° 旋转码：标签底色区域呈竖排（高>宽）分布；水平码保持横排（回归）。"""
    sys.path.insert(0, str(IMG_DIR.parent))
    from gen_test_images import make_barcode, pad
    img = pad(make_barcode("VERT-90-TEST", "Code128", 480, 150), 30)
    rotated = img.rotate(-90, expand=True, fillcolor=255)
    path = tmp_path / "vert90.png"
    rotated.save(path)

    win = _make_window(tmp_path)
    win.add_paths([str(path)])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()

    pix = win.preview.pixmap()
    assert not pix.isNull()
    img_q = pix.toImage()
    # 标签底色（半透明深底叠在白底上 → 灰 60-140）像素的分布
    pts = [(x, y) for x in range(img_q.width()) for y in range(img_q.height())
           if (lambda c: 50 < c.red() < 140 and abs(c.red() - c.green()) < 8
               and abs(c.green() - c.blue()) < 8)(img_q.pixelColor(x, y))]
    assert pts, "未找到标签底色像素"
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = max(xs) - min(xs) + 1
    h = max(ys) - min(ys) + 1
    assert h > w, f"标签应呈竖排分布（高 {h} > 宽 {w}）"

    # 回归：水平码标签仍横排（宽>高）
    win2 = _make_window(tmp_path / "h")
    win2.add_paths([str(IMG_DIR / "code128_a.png")])
    win2._pool.waitForDone(30000)
    qapp.processEvents()
    win2.file_list.setCurrentRow(0)
    qapp.processEvents()
    img2 = win2.preview.pixmap().toImage()
    pts2 = [(x, y) for x in range(img2.width()) for y in range(img2.height())
            if (lambda c: 50 < c.red() < 140 and abs(c.red() - c.green()) < 8
                and abs(c.green() - c.blue()) < 8)(img2.pixelColor(x, y))]
    assert pts2
    xs2 = [p[0] for p in pts2]
    ys2 = [p[1] for p in pts2]
    assert (max(xs2) - min(xs2) + 1) > (max(ys2) - min(ys2) + 1), "水平码标签应保持横排"
    win.close()
    win2.close()
