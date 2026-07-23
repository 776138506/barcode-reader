"""标注增强测试：N: 内容 标签、截断、底色块、三态样式、主预览/F1 一致性。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsRectItem, QGraphicsSimpleTextItem  # noqa: E402

from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui.preview_window import (Frame, build_frames, frame_label,  # noqa: E402
                               label_placement, label_style)

IMG_DIR = Path(__file__).resolve().parent / "images"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _frame(content="abc", seq=1, suspect=False, points=None):
    return Frame(points=points or [(20, 30), (120, 30), (120, 90), (20, 90)],
                 seq=seq, suspect=suspect, content=content)


def _make_window(tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    return mw.MainWindow(settings=settings, history_db=tmp_path / "h.db",
                         profile_store=ProfileStore(tmp_path / "p.json"),
                         template_store=TemplateStore(tmp_path / "t.json"))


# ---------- 标签文本 ----------

def test_label_text_normal_suspect():
    assert frame_label(_frame("abc", 1)) == "1: abc"
    assert frame_label(_frame("abc", 2, suspect=True)) == "2?: abc"


def test_label_truncation():
    long25 = "x" * 25
    assert frame_label(_frame(long25, 3)) == "3: " + "x" * 24 + "…"
    exact24 = "y" * 24
    assert frame_label(_frame(exact24, 3)) == "3: " + exact24  # 24 字符不截断


# ---------- 三态样式 ----------

def test_label_style_states():
    f = _frame("abc", 1)
    bg, text, bold = label_style(f, "normal")
    assert (bg.red(), bg.green(), bg.blue(), bg.alpha()) == (0, 0, 0, 165)
    assert text.alpha() == 255 and not bold

    bg_s, _, _ = label_style(_frame("abc", 1, suspect=True), "normal")
    assert bg_s.red() == 150 and bg_s.green() == 125 and bg_s.alpha() == 165

    bg_h, text_h, bold_h = label_style(f, "highlight")
    assert (bg_h.red(), bg_h.green(), bg_h.alpha()) == (255, 140, 255)
    assert bold_h and text_h.alpha() == 255

    bg_d, text_d, bold_d = label_style(f, "dim")
    assert bg_d.alpha() == 40 and text_d.alpha() == 60 and not bold_d


def test_label_placement():
    # 框上方有空间 → 紧贴框上方
    x, y = label_placement(20, 100, 100, 60, 50, 14)
    assert y == 100 - 14 - 2
    # 框贴图片顶（上方出界）→ 放框内左上
    x2, y2 = label_placement(20, 5, 100, 60, 50, 14)
    assert y2 == 5 + 2


# ---------- 主预览像素断言 ----------

def _count_pred(pixmap, pred) -> int:
    img = pixmap.toImage()
    return sum(1 for x in range(img.width()) for y in range(img.height())
               if pred(img.pixelColor(x, y)))


def test_main_preview_label_bg(qapp, tmp_path):
    """标签底色块存在（白图上出现非纯图内容的暗灰区）；高亮橙底；dim 变淡。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()

    pix = win.preview.pixmap()
    dark_bg = _count_pred(pix, lambda c: 50 < c.red() < 140
                          and abs(c.red() - c.green()) < 8
                          and abs(c.green() - c.blue()) < 8)
    assert dark_bg > 20, "未找到半透明深色标签底"

    content = win.results[str(IMG_DIR / "qr_hello.png")][0].content
    win.preview.set_highlight(content)
    qapp.processEvents()
    pix_h = win.preview.pixmap()
    orange_bg = _count_pred(pix_h, lambda c: c.red() > 200
                            and 100 < c.green() < 180 and c.blue() < 60)
    assert orange_bg > 40, "高亮标签橙底未出现"

    win.preview.set_highlight("别的内容")  # 当前帧进入 dim
    qapp.processEvents()
    pix_d = win.preview.pixmap()
    # dim 底色 alpha 40 → 白图上灰度 ~215，比正常底（~89）亮
    light_bg = _count_pred(pix_d, lambda c: 190 < c.red() < 235
                           and abs(c.red() - c.green()) < 8
                           and abs(c.green() - c.blue()) < 8)
    assert light_bg > 20, "dim 标签未变淡"
    win.close()


# ---------- F1 一致性 ----------

def test_f1_label_items_consistent(qapp, tmp_path):
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()
    win.open_preview_window()
    qapp.processEvents()
    pw = win._preview_window

    frames = pw._frames
    assert len(frames) == 1
    # 每帧 3 个 item：多边形 + 底色矩形 + 文本
    assert len(pw._frame_items) == 3
    texts = [i for i in pw._frame_items if isinstance(i, QGraphicsSimpleTextItem)]
    rects = [i for i in pw._frame_items if isinstance(i, QGraphicsRectItem)]
    assert len(texts) == 1 and len(rects) == 1
    # 文本与主预览同源（同一 frame_label）
    assert texts[0].text() == frame_label(frames[0])
    # 底色矩形颜色 = label_style 底色
    bg, _, _ = label_style(frames[0], "normal")
    assert rects[0].brush().color() == bg

    # 高亮态：底色矩形变橙
    pw.set_highlight(frames[0].content)
    qapp.processEvents()
    rects_h = [i for i in pw._frame_items if isinstance(i, QGraphicsRectItem)]
    assert rects_h[0].brush().color().red() == 255
    assert rects_h[0].brush().color().alpha() == 255
    pw.close()
    win.close()
