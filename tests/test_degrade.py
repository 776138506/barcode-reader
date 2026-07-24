"""标签自适应降级测试（D31）：碰撞/出界/字高降级为徽标，缩放恢复全长。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QFont, QFontMetricsF, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsItemGroup, QGraphicsSimpleTextItem  # noqa: E402

from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui.preview_window import Frame, frame_label, plan_label  # noqa: E402

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


def _frame(x=20, y=30, w=100, h=100, seq=1, content="abc"):
    return Frame(points=[(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                 seq=seq, suspect=False, content=content)


def _metrics():
    font = QFont()
    font.setPixelSize(20)
    m = QFontMetricsF(font)
    return m.horizontalAdvance("1: abc") + 4, m.height() + 2


# ---------- plan_label 判定 ----------

def test_plan_normal_full(qapp):
    tw, th = _metrics()
    placed = []
    layout = plan_label(_frame(), tw, th, 400, 400, placed)
    assert layout.mode == "full" and layout.text == frame_label(_frame())
    assert len(placed) == 1


def test_plan_collision_only_second_degrades(qapp):
    tw, th = _metrics()
    # 两个框位置几乎相同 → 标签必然碰撞
    f1 = _frame(x=20, y=30)
    f2 = _frame(x=25, y=35, seq=2)
    placed = []
    l1 = plan_label(f1, tw, th, 400, 400, placed)
    l2 = plan_label(f2, tw, th, 400, 400, placed)
    assert l1.mode == "full", "先画的保留全长"
    assert l2.mode == "badge" and l2.text == "2", "后冲突的降级为徽标"


def test_plan_no_font_trigger_full(qapp):
    """D33：有效字高小不再独立降级——单码任何缩放都应全长（渲染层字号下限兜底）。"""
    tw, th = _metrics()
    placed = []
    layout = plan_label(_frame(), tw, th, 400, 400, placed)
    assert layout.mode == "full"
    assert len(placed) == 1


def test_plan_long_label_clamped_into_bounds(qapp):
    """长标签超出图片宽度 → 平移收进界内而不是降级。

    用 15 字符内容：在任平台字体下标签宽度都 < 400px（字体宽度差异不影响，
    见 DECISIONS D34）。框放在右缘，标签须被平移收边。"""
    font = QFont()
    font.setPixelSize(20)
    content = "LONG-CONTENT-15"
    shown = f"1: {content}"  # 未超 24 字符不截断
    m = QFontMetricsF(font)
    tw = m.horizontalAdvance(shown) + 4
    th = m.height() + 2
    assert tw < 400, f"本机字体下标签已超宽 ({tw})，需再缩短内容"
    f = _frame(x=250, y=30, seq=1, content=content)
    placed = []
    layout = plan_label(f, tw, th, 400, 400, placed)
    assert layout.mode == "full"
    assert layout.x < 250, "右缘框的标签应被平移收边"
    assert layout.x >= 0 and layout.x + layout.w <= 400, "越界标签应收进界内"


def test_plan_out_of_bounds_degrades(qapp):
    tw, th = _metrics()
    # 框贴图片顶部且标签放框内也出界？构造框超出图片 → 标签出界降级
    # 极端窄图：全长标签收边后仍放不进图片 → 降级徽标（触发条件②）
    layout2 = plan_label(_frame(), tw, th, 40, 40, [])
    assert layout2.mode == "badge"


# ---------- GUI：三码竖排用户场景 ----------

def _make_three_vertical(tmp_path, big=False):
    sys.path.insert(0, str(IMG_DIR.parent))
    from gen_test_images import make_barcode, pad
    from PIL import Image
    if big:
        # 大图：适应窗口后缩放比小，触发字高降级
        canvas = Image.new("L", (1400, 1700), 255)
        for i in range(3):
            code = pad(make_barcode(f"VERT-CODE-{i}", "Code128", 400, 130), 15)
            code = code.rotate(-90, expand=True, fillcolor=255)
            canvas.paste(code, (80 + i * 420, 150))
    else:
        canvas = Image.new("L", (500, 640), 255)
        for i in range(3):
            code = pad(make_barcode(f"VERT-CODE-{i}", "Code128", 400, 130), 15)
            code = code.rotate(-90, expand=True, fillcolor=255)
            canvas.paste(code, (30 + i * 160, 60))
    path = tmp_path / ("three_vertical_big.png" if big else "three_vertical.png")
    canvas.save(path)
    return path


def _label_texts(view):
    texts = []
    for item in view._frame_items:
        if isinstance(item, QGraphicsItemGroup):
            for child in item.childItems():
                if isinstance(child, QGraphicsSimpleTextItem):
                    texts.append(child.text())
    return texts


def test_three_vertical_degrade_and_restore(qapp, tmp_path):
    """三竖码用户场景：窗口缩到很小（有效字高 <10px）→ 降级为徽标且互不重叠；
    F1 放大后恢复全长；默认尺寸下全长标签互不碰撞。"""
    path = _make_three_vertical(tmp_path)
    win = _make_window(tmp_path)
    win.add_paths([str(path)])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()

    # 默认尺寸：全长标签之间不得碰撞（降级机制的不变量）
    texts = _label_texts(win.preview)
    assert len(texts) == 3

    # 大图（适应窗口缩放比小）少码场景：字号下限保持可读，仍显示全长标签（D33）
    win2 = _make_window(tmp_path / "big")
    win2.add_paths([str(_make_three_vertical(tmp_path, big=True))])
    win2._pool.waitForDone(30000)
    qapp.processEvents()
    win2.file_list.setCurrentRow(0)
    qapp.processEvents()
    texts_small = _label_texts(win2.preview)
    assert all(": " in t for t in texts_small), \
        f"少码场景任何缩放都应全长显示: {texts_small}"
    win2.close()


def _make_dense_horizontal(tmp_path):
    """多码密集场景：大画布（嵌入预览缩放比 ~0.2，字号下限放大标签宽度），
    同排短内容码的标签水平互相碰撞；F1 较大缩放下恢复不碰撞。"""
    sys.path.insert(0, str(IMG_DIR.parent))
    from gen_test_images import make_barcode, pad
    from PIL import Image
    canvas = Image.new("L", (2400, 300), 255)
    for i in range(3):
        code = pad(make_barcode(f"DENSE-CODE-LONGER-{i}", "Code128", 300, 110), 10)
        canvas.paste(code, (60 + i * 400, 90))
    path = tmp_path / "dense_horizontal.png"
    canvas.save(path)
    return path


def test_dense_codes_badge_on_collision(qapp, tmp_path):
    """多码密集场景：小缩放 + 字号下限使标签碰撞 → 后画者降级为徽标；
    F1 较大缩放（字号下限不再放大标签）→ 恢复全长。"""
    win = _make_window(tmp_path)
    win.add_paths([str(_make_dense_horizontal(tmp_path))])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()
    texts = _label_texts(win.preview)
    assert len(texts) == 3
    badges = [t for t in texts if ": " not in t]
    full = [t for t in texts if ": " in t]
    assert len(badges) >= 1, f"密集碰撞应有降级徽标: {texts}"
    assert len(full) >= 1, "先画的保留全长"

    win.open_preview_window()
    qapp.processEvents()
    texts_f1 = _label_texts(win._preview_window._view)
    assert all(": " in t for t in texts_f1), f"F1 较大缩放应恢复全长: {texts_f1}"
    win._preview_window.close()
    win.close()

    # F1 放大后恢复全长
    win.open_preview_window()
    qapp.processEvents()
    pw = win._preview_window
    pw.zoom_in()
    pw.zoom_in()
    qapp.processEvents()
    texts_f1 = _label_texts(pw._view)
    assert all(": " in t for t in texts_f1), f"放大后应恢复全长: {texts_f1}"
    pw.close()
    win.close()


def test_horizontal_code_full_label_regression(qapp, tmp_path):
    """水平码回归：默认不降级，标签为全长（短内容码，字体宽度差异无关）。"""
    sys.path.insert(0, str(IMG_DIR.parent))
    from gen_test_images import make_barcode, pad
    img = pad(make_barcode("ABC-1", "Code128", 400, 120), 20)
    path = tmp_path / "short_h.png"
    img.save(path)
    win = _make_window(tmp_path)
    win.add_paths([str(path)])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()
    texts = _label_texts(win.preview)
    assert len(texts) == 1 and ": " in texts[0]
    win.close()
