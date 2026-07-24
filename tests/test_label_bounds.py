"""分场景标签策略（F1 全长）与四方向出界翻转测试（D39）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtGui import QFont, QFontMetricsF, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsItemGroup, QGraphicsSimpleTextItem  # noqa: E402

from decoder import DecodeResult  # noqa: E402
from ui.preview_window import (Frame, PreviewView, build_frames, frame_label,  # noqa: E402
                               frame_angle, rotated_label_anchor)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _label_texts(view):
    texts = []
    for item in view._frame_items:
        if isinstance(item, QGraphicsItemGroup):
            for child in item.childItems():
                if isinstance(child, QGraphicsSimpleTextItem):
                    texts.append(child.text())
    return texts


# ---------- F1（交互模式）永远全长 ----------

def test_f1_interactive_always_full_label(qapp):
    """F1 交互模式：小缩放下标签也不省略、不降级徽标（D39）。"""
    view = PreviewView(None, interactive=True)
    view.resize(300, 200)  # 小视口 → 小缩放
    content = "83072360103094471143"  # 20 位长内容
    r = DecodeResult(content=content, format="Code128",
                     position=[(50, 100), (450, 100), (450, 200), (50, 200)])
    view.set_image(QPixmap(500, 500), build_frames([r], 12))
    qapp.processEvents()
    texts = _label_texts(view)
    assert len(texts) == 1
    assert texts[0] == frame_label(view._frames[0]) == f"12: {content}", \
        f"F1 应永远全长: {texts[0]!r}"
    assert "…" not in texts[0], "F1 不得省略"


def test_f1_no_badge_for_tiny_box(qapp):
    """F1 交互模式：极小的框也不降级徽标（主预览同场景是徽标，对照）。"""
    view = PreviewView(None, interactive=True)
    view.resize(300, 200)
    r = DecodeResult(content="TINY-CONTENT-123", format="QRCode",
                     position=[(100, 100), (130, 100), (130, 130), (100, 130)])
    view.set_image(QPixmap(500, 500), build_frames([r], 3))
    qapp.processEvents()
    texts = _label_texts(view)
    assert texts == ["3: TINY-CONTENT-123"], f"F1 不得降级徽标: {texts}"


def test_embedded_elision_unchanged(qapp):
    """主预览（嵌入模式）省略链回归不变：小缩放下长内容仍省略为 `前…后`。"""
    view = PreviewView(None, interactive=False)
    view.resize(300, 200)
    content = "83072360103094471143"
    r = DecodeResult(content=content, format="Code128",
                     position=[(50, 100), (250, 100), (250, 200), (50, 200)])
    view.set_image(QPixmap(500, 500), build_frames([r], 7))
    qapp.processEvents()
    texts = _label_texts(view)
    assert len(texts) == 1
    assert "…" in texts[0], f"主预览应继续等长省略: {texts[0]!r}"
    assert texts[0].startswith("7: 83")
    assert texts[0].endswith("43")


# ---------- 四方向出界翻转/收边 ----------

def _rot_label_corners(x, y, angle, w, h):
    import math
    t = math.radians(angle)
    e = (math.cos(t), math.sin(t))
    m = (-math.sin(t), math.cos(t))
    return [(x + u * e[0] + v * m[0], y + u * e[1] + v * m[1])
            for u in (0, w) for v in (0, h)]


def _in_bounds(corners, w, h):
    return all(0 <= px <= w and 0 <= py <= h for px, py in corners)


@pytest.mark.parametrize("edge", ["top", "bottom", "left", "right"])
def test_rotated_label_flips_all_edges(qapp, edge):
    """旋转标签贴图片四边时不得被裁断：翻转或平移收进界内（D39）。"""
    # 竖向长框（90° 码），分别贴近四边
    boxes = {
        "top": [(50, 5), (50, 300), (10, 300), (10, 5)],        # 贴图顶
        "bottom": [(50, 495), (50, 200), (10, 200), (10, 495)],  # 贴图底
        "left": [(5, 100), (5, 300), (-15, 300), (-15, 100)],    # 部分出左界
        "right": [(400, 100), (400, 300), (380, 300), (380, 100)],  # 贴图右
    }
    frame = Frame(points=boxes[edge], seq=1, suspect=False,
                  content="EDGE-TEST-CONTENT")
    font = QFont()
    font.setPixelSize(20)
    m = QFontMetricsF(font)
    tw = m.horizontalAdvance(frame_label(frame)) + 4
    th = m.height() + 2
    img_w, img_h = 400, 500
    ax, ay, angle = rotated_label_anchor(frame, frame_angle(frame),
                                         tw, th, img_w, img_h)
    corners = _rot_label_corners(ax, ay, angle, tw, th)
    assert _in_bounds(corners, img_w, img_h), \
        f"{edge} 边标签被裁断: 锚点=({ax:.0f},{ay:.0f}) corners={corners}"


def test_vertical_code_at_image_top_label_visible(qapp, tmp_path):
    """实图场景：竖排码贴图顶，标签完整可见（不被裁断）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "images" / ".."))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent)
                    and str(Path(__file__).resolve().parent.parent / "../barcode-reader/tests")
    )
    from gen_test_images import make_barcode, pad
    from PIL import Image
    code = pad(make_barcode("83072360103094471143", "Code128", 400, 130), 10)
    code = code.rotate(-90, expand=True, fillcolor=255)
    canvas = Image.new("L", (500, 500), 255)
    canvas.paste(code, (150, 2))  # 贴图顶
    path = tmp_path / "top_edge.png"
    canvas.save(path)

    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from profiles import ProfileStore
    from templates import TemplateStore
    from PySide6.QtCore import QSettings
    from ui import main_window as mw
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=tmp_path / "h.db",
                        profile_store=ProfileStore(tmp_path / "p.json"),
                        template_store=TemplateStore(tmp_path / "t.json"))
    win.add_paths([str(path)])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()

    texts = _label_texts(win.preview)
    assert len(texts) == 1
    # 标签文本完整（省略形式或全长都行，但必须含头尾）
    t = texts[0]
    assert t.startswith("1: 83"), f"头部缺失: {t!r}"
    assert t.endswith("43"), f"尾部缺失: {t!r}"
    # 标签渲染矩形在图片内（几何断言，不依赖像素）
    from ui.preview_window import plan_label, frame_angle, rotated_label_anchor, Frame
    frame = win.preview._frames[0]
    font = QFont()
    font.setPixelSize(20)
    m = QFontMetricsF(font)
    from ui.preview_window import frame_label as fl
    tw = m.horizontalAdvance(fl(frame)) + 4
    th = m.height() + 2
    ax, ay, angle = rotated_label_anchor(frame, frame_angle(frame),
                                         tw, th, 500, 500)
    corners = _rot_label_corners(ax, ay, angle, tw, th)
    assert _in_bounds(corners, 500, 500), "贴图顶标签应完整收进界内"
    win.close()
