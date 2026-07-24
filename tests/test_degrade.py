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


def _font(px=20):
    font = QFont()
    font.setPixelSize(px)
    return font


def _edge_for(text, px=20, margin=40):
    """字体驱动：按本地 QFontMetrics 实测文本宽度构造框长边（D40）。
    任何平台字体下 full 判定都确定（标签宽 + margin 余量）。"""
    m = QFontMetricsF(_font(px))
    return m.horizontalAdvance(text) + 4 + margin


def _frame_edge(x, y, edge, seq=1, content="abc", h=100):
    return Frame(points=[(x, y), (x + edge, y), (x + edge, y + h), (x, y + h)],
                 seq=seq, suspect=False, content=content)


# ---------- plan_label 判定 ----------

def test_plan_normal_full(qapp):
    f = _frame_edge(20, 30, _edge_for("1: abc"), content="abc")
    placed = []
    layout = plan_label(f, _font(), 400, 400, placed)
    assert layout.mode == "full" and layout.text == frame_label(f)
    assert len(placed) == 1


def test_plan_collision_only_second_degrades(qapp):
    # 两个框位置几乎相同 → 标签必然碰撞（宽度字体驱动，任何平台都撞）
    f1 = _frame_edge(20, 30, _edge_for("1: abc"), content="abc")
    f2 = _frame_edge(25, 35, _edge_for("2: abc"), seq=2, content="abc")
    placed = []
    l1 = plan_label(f1, _font(), 400, 400, placed)
    l2 = plan_label(f2, _font(), 400, 400, placed)
    assert l1.mode == "full", "先画的保留全长"
    assert l2.mode == "badge" and l2.text == "2", "后冲突的降级为徽标"


def test_plan_no_font_trigger_full(qapp):
    """D33：有效字高小不再独立降级——单码任何缩放都应全长（渲染层字号下限兜底）。"""
    f = _frame_edge(20, 30, _edge_for("1: abc"), content="abc")
    placed = []
    layout = plan_label(f, _font(), 400, 400, placed)
    assert layout.mode == "full"
    assert len(placed) == 1


def test_plan_long_label_elided_to_box_edge(qapp):
    """等长省略（D35）：全长标签超过框长边 → 中间省略到 ≤ 框长边。"""
    content = "LONG-CONTENT-15"
    f = _frame(x=250, y=30, seq=1, content=content)  # 框长边 100px
    placed = []
    layout = plan_label(f, _font(), 400, 400, placed)
    assert layout.mode == "full"
    assert "…" in layout.text, f"长内容应被省略: {layout.text!r}"
    assert layout.w <= 104, f"省略后标签宽度应 ≤ 框长边: {layout.w}"
    assert layout.text.startswith("1: ")
    assert layout.text.endswith("5"), "省略应保留尾部字符"


def test_plan_out_of_bounds_degrades(qapp):
    # 极端窄图（40x40）：省略后标签放置仍出图片边界 → 降级徽标（触发条件②）
    layout2 = plan_label(_frame(), _font(), 40, 40, [])
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


def test_tiny_box_degrades_to_badge(qapp, tmp_path):
    """极小的框：最短省略形式 `N: a…b` 仍超框长边 → 降级徽标（GUI 兜底路径）。"""
    sys.path.insert(0, str(IMG_DIR.parent))
    import numpy as np
    import zxingcpp
    from PIL import Image
    b = zxingcpp.create_barcode("TINYBOX-CONTENT", zxingcpp.BarcodeFormat.QRCode)
    img = Image.fromarray(np.array(b.to_image()))  # 小模块 QR，框长边很小
    path = tmp_path / "tiny_qr.png"
    img.save(path)
    win = _make_window(tmp_path)
    win.add_paths([str(path)])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()
    texts = _label_texts(win.preview)
    assert len(texts) == 1
    assert ": " not in texts[0], f"极小框应降级为徽标: {texts[0]!r}"
    assert texts[0] == "1"
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


def test_elide_levels_and_restore(qapp):
    """逐级省略与恢复（D35）：目标宽度越大省略越少，头尾始终保留。"""
    from ui.preview_window import elide_label
    content = "ABCDEFGHIJKLMNOP"  # 16 字符
    f = _frame(seq=1, content=content)
    font = _font()
    from PySide6.QtGui import QFontMetricsF
    m = QFontMetricsF(font)
    full = frame_label(f)
    full_w = m.horizontalAdvance(full) + 4

    # 空间充足 → 全长
    assert elide_label(f, font, full_w + 50) == full
    # 逐级收紧：文本长度单调不增、头尾保留
    prev_len = len(full)
    for target in (full_w * 0.7, full_w * 0.5, full_w * 0.35):
        text = elide_label(f, font, target)
        assert text is not None
        assert "…" in text
        assert text.startswith("1: A"), f"头部保留: {text!r}"
        assert text.endswith("P"), f"尾部保留: {text!r}"
        assert len(text) <= prev_len, f"逐级应单调缩短: {text!r}"
        prev_len = len(text)
    # 恢复（放宽目标）→ 回到全长
    assert elide_label(f, font, full_w + 50) == full


def test_elide_min_form_and_badge(qapp):
    """最短形式 `N: a…b`；仍放不下 → None（徽标兜底）。"""
    from ui.preview_window import elide_label
    f = _frame(seq=9, content="XYZABC")
    font = _font()
    from PySide6.QtGui import QFontMetricsF
    m = QFontMetricsF(font)
    min_w = m.horizontalAdvance("9: X…C") + 4
    # 刚好容下最短形式
    assert elide_label(f, font, min_w + 1) == "9: X…C"
    # 连最短形式都放不下
    assert elide_label(f, font, min_w - 10) is None


def test_three_vertical_elide_equal_length(qapp, tmp_path):
    """竖排三码（20 位内容）小缩放：三标签均省略为 `前…后` 且与各自框等长（D35）。"""
    sys.path.insert(0, str(IMG_DIR.parent))
    from gen_test_images import make_barcode, pad
    from PIL import Image
    canvas = Image.new("L", (1400, 1700), 255)
    contents = ["86316420001266495057", "86316420001266482464", "86316420001266475982"]
    for i, c in enumerate(contents):
        code = pad(make_barcode(c, "Code128", 400, 130), 15)
        code = code.rotate(-90, expand=True, fillcolor=255)
        canvas.paste(code, (80 + i * 420, 150))
    path = tmp_path / "three_vertical_elide.png"
    canvas.save(path)

    win = _make_window(tmp_path)
    win.add_paths([str(path)])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()

    texts = _label_texts(win.preview)
    assert len(texts) == 3, f"应三个标签: {texts}"
    for i, t in enumerate(texts):
        assert "…" in t, f"长内容应省略: {t!r}"
        # 语义断言（D40）：序号 + 至少一个内容首字符 + 尾部两位，不硬编码省略深度
        assert t.startswith(f"{i + 1}: {contents[i][0]}"), f"头部保留: {t!r}"
        assert t.endswith(contents[i][-2:]), f"尾部保留: {t!r}"

    # 等长断言：布局宽度 ≈ 各自框长边（本机字体实测，不用硬编码宽度）
    import math
    from ui.preview_window import frame_long_edge, plan_label, label_font_size
    scale = win.preview._effective_font_scale()
    for frame in win.preview._frames:
        xs = [p[0] for p in frame.points]
        ys = [p[1] for p in frame.points]
        box_w = max(xs) - min(xs)
        box_h = max(ys) - min(ys)
        font_px = max(label_font_size(box_w, box_h), math.ceil(10 / scale))
        layout = plan_label(frame, _font(font_px), canvas.size[0], canvas.size[1], [])
        edge = frame_long_edge(frame)
        assert layout.mode == "full"
        assert layout.w <= edge + 6, f"标签应 ≤ 框长边: {layout.w} > {edge}"
        assert layout.w >= edge * 0.5, f"标签不应过度省略: {layout.w} << {edge}"
    win.close()
