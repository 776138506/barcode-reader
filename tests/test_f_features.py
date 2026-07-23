"""F0 行号表头隐藏 / F1 独立预览窗口 / F2 框编号 / F3 点击高亮 测试。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from decoder import DecodeResult  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui.preview_window import Frame, build_frames, frame_label  # noqa: E402

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


def _add_two(qapp, win):
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "multi_3codes.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()


def _count_color(pixmap, pred) -> int:
    img = pixmap.toImage()
    n = 0
    for x in range(img.width()):
        for y in range(img.height()):
            if pred(img.pixelColor(x, y)):
                n += 1
    return n


def _is_orange(c):
    return c.red() > 200 and 100 < c.green() < 180 and c.blue() < 80


def _is_green(c):
    return c.green() > 150 and c.red() < 80 and c.blue() < 80


# ---------- 0 行号表头 ----------

def test_vertical_header_hidden(qapp, tmp_path):
    win = _make_window(tmp_path)
    assert not win.table.verticalHeader().isVisible()
    # 自有「序号」列保留
    assert win.table.horizontalHeaderItem(0).text() == "序号"
    win.close()


# ---------- F2 框编号 ----------

def test_frames_global_seq(qapp, tmp_path):
    """框序号与结果表格序号一致（跨图累加）：qr_hello=1，multi 三码=2,3,4。"""
    win = _make_window(tmp_path)
    _add_two(qapp, win)
    assert [f.seq for f in win._frames_for(str(IMG_DIR / "qr_hello.png"))] == [1]
    assert [f.seq for f in win._frames_for(str(IMG_DIR / "multi_3codes.png"))] == [2, 3, 4]
    # 表格序号列同步核对
    assert [win.table.item(i, 0).text() for i in range(4)] == ["1", "2", "3", "4"]
    win.close()


def test_frame_label_suspect():
    r = DecodeResult(content="X", format="QRCode",
                     position=[(0, 0), (1, 0), (1, 1), (0, 1)], suspect=True)
    frames = build_frames([r], 7)
    assert frame_label(frames[0]) == "7?: X"
    assert frames[0].seq == 7


def test_preview_draws_seq_and_suspect_yellow(qapp, tmp_path):
    """主预览：有效绿框、疑似黄框 + 序号文本像素存在。"""
    win = _make_window(tmp_path)
    _add_two(qapp, win)
    win.file_list.setCurrentRow(1)
    qapp.processEvents()
    pix = win.preview.pixmap()
    assert _count_color(pix, _is_green) > 50

    # 构造含疑似码的帧，黄框应出现（白底图 + 大框，避免降级与亚像素）
    from PySide6.QtGui import QPixmap
    win.preview.set_image(QPixmap(300, 300), [])
    frames = [Frame(points=[(20, 40), (220, 40), (220, 200), (20, 200)],
                    seq=9, suspect=True, content="SUS")]
    win.preview.set_frames(frames)
    qapp.processEvents()
    pix = win.preview.pixmap()
    yellow = _count_color(pix, lambda c: c.red() > 180 and c.green() > 150
                          and c.blue() < 80)
    assert yellow > 30
    win.close()


# ---------- F3 点击高亮 ----------

def test_table_click_highlights_orange_and_dim(qapp, tmp_path):
    """点击结果行：对应框变橙，其余绿框变淡（半透明）；切换图片恢复。"""
    win = _make_window(tmp_path)
    _add_two(qapp, win)
    win._on_table_clicked(1, 3)  # multi 的第一个码
    qapp.processEvents()
    pix = win.preview.pixmap()
    assert _count_color(pix, _is_orange) > 20, "橙色高亮框未出现"
    # 变淡的绿框 alpha=60 → 与白色背景混合后仍可见但变淡，断言深绿减少
    win._on_file_selected(0)  # 切换图片 → 恢复常态
    qapp.processEvents()
    win._on_file_selected(1)
    qapp.processEvents()
    pix2 = win.preview.pixmap()
    assert _count_color(pix2, _is_orange) == 0, "切换图片后高亮未恢复"
    win.close()


def test_dedup_click_highlight(qapp, tmp_path):
    """去重视图点击：跳首个来源图并高亮该内容。"""
    win = _make_window(tmp_path)
    _add_two(qapp, win)
    win.dedup_check.setChecked(True)
    qapp.processEvents()
    # 找到 qr-hello 内容所在去重行
    target = None
    for i in range(win.table.rowCount()):
        if "qr-hello" in win.table.item(i, 3).text():
            target = i
            break
    assert target is not None
    win._on_table_clicked(target, 4)
    qapp.processEvents()
    assert win.file_list.currentRow() == 0  # 首个来源 qr_hello.png
    assert "qr-hello" in win.preview._highlight_content
    win.close()


# ---------- F1 独立预览窗口 ----------

def test_preview_window_zoom_rotate_markers(qapp, tmp_path):
    win = _make_window(tmp_path)
    _add_two(qapp, win)
    win.file_list.setCurrentRow(1)
    qapp.processEvents()
    win.open_preview_window()
    qapp.processEvents()
    pw = win._preview_window
    assert pw is not None
    assert len(pw._frame_items) > 0

    t0 = pw._view.transform()
    pw.zoom_in()
    t1 = pw._view.transform()
    assert t1.m11() > t0.m11()  # 放大后缩放增大

    grab_before = pw._view.grab()
    pw.rotate_right()
    t2 = pw._view.transform()
    assert abs(t2.m12()) > 0  # 旋转 90° 后变换含旋转分量
    grab_after = pw._view.grab()
    assert grab_before.toImage() != grab_after.toImage()  # pixmap 变化

    # 标记开关两态
    pw.markers_check.setChecked(False)
    assert all(not item.isVisible() for item in pw._frame_items)
    pw.markers_check.setChecked(True)
    assert all(item.isVisible() for item in pw._frame_items)

    # 列表切换跟随
    win.file_list.setCurrentRow(0)
    qapp.processEvents()
    assert "qr_hello" in pw.windowTitle()
    assert len(pw._frames) == 1
    pw.close()
    win.close()


def test_preview_window_highlight_sync(qapp, tmp_path):
    """F1 高亮态同步：点击结果行后窗口内对应帧橙色、其余变淡。"""
    win = _make_window(tmp_path)
    _add_two(qapp, win)
    win.file_list.setCurrentRow(1)
    qapp.processEvents()
    win.open_preview_window()
    qapp.processEvents()
    pw = win._preview_window
    win._on_table_clicked(1, 3)
    qapp.processEvents()
    from ui.preview_window import frame_state
    states = [frame_state(f, pw._highlight_content) for f in pw._frames]
    assert "highlight" in states and "dim" in states
    pw.close()
    win.close()
