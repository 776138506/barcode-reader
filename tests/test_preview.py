"""预览区回归测试：点击列表/表格定位、高亮框像素、加载失败不残留旧图。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import main_window as mw  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    return mw.MainWindow(settings=settings, history_db=tmp_path / "h.db", **_stores(tmp_path))


def _green_pixels(pixmap) -> int:
    img = pixmap.toImage()
    n = 0
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            if c.green() > 150 and c.red() < 80 and c.blue() < 80:
                n += 1
    return n


def test_preview_on_list_and_table_click(qapp, tmp_path):
    """点列表项/普通视图表格行/去重视图表格行，预览都有图且画识别框。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "qr_rotated180.png"),
                   str(IMG_DIR / "code128_a.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()

    win.file_list.setCurrentRow(0)
    qapp.processEvents()
    pix = win.preview.pixmap()
    assert pix is not None and not pix.isNull()
    assert _green_pixels(pix) > 50, "识别框未绘制"

    # 普通视图点表格行 → 预览定位到对应图
    win._on_table_clicked(1, 3)
    qapp.processEvents()
    assert win.file_list.currentRow() == 1
    assert win.preview.pixmap() is not None and not win.preview.pixmap().isNull()

    # 去重视图点表格行 → 预览定位到首个来源图
    win.dedup_check.setChecked(True)
    qapp.processEvents()
    win._on_table_clicked(0, 4)
    qapp.processEvents()
    assert win.file_list.currentRow() == 0
    assert win.preview.pixmap() is not None and not win.preview.pixmap().isNull()
    win.close()


def test_preview_missing_file_shows_message_not_stale(qapp, tmp_path):
    """加载失败的预览必须清空旧图并提示，不得残留上一张。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()
    assert not win.preview.pixmap().isNull()  # 已有一张正常预览

    win.preview.show_image(str(tmp_path / "不存在.png"), [])
    assert win.preview.pixmap().isNull(), "残留了上一张图"
    assert "无法加载图片" in win.preview.text()
    win.close()


def test_preview_updates_when_current_item_decoded(qapp, tmp_path):
    """解码完成前选中的项，解码后自动补画识别框。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png")])
    win.file_list.setCurrentRow(0)  # 解码完成前选中
    qapp.processEvents()
    win._pool.waitForDone(30000)
    qapp.processEvents()
    pix = win.preview.pixmap()
    assert pix is not None and not pix.isNull()
    assert _green_pixels(pix) > 50, "解码完成后未补画识别框"
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}


def test_preview_survives_removing_unselected(qapp, tmp_path):
    """复现路径：2 图选中 B，移除未选中的 A → 预览不该被清（现状红）。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "code128_a.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(1)  # 选中 code128
    qapp.processEvents()
    assert not win.preview.pixmap().isNull()

    win._remove_item(win.file_list.item(0))  # 移除未选中的 qr_hello
    qapp.processEvents()
    assert not win.preview.pixmap().isNull(), "移除未选中项误清了预览"
    win.close()


def test_preview_single_remaining_clickable(qapp, tmp_path):
    """复现路径：2 图选中 B，移除未选中的 A 后预览被清 → 点剩下的 B 必须能恢复（现状红）。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "code128_a.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(1)
    qapp.processEvents()
    win._remove_item(win.file_list.item(0))
    qapp.processEvents()
    # 修复后：移除动作本身就该恢复剩余选中项的预览，无需任何额外点击
    assert win.file_list.count() == 1
    assert not win.preview.pixmap().isNull(), "剩余单图无法预览"
    win.close()


def test_preview_after_removing_selected(qapp, tmp_path):
    """移除正在预览的选中项 → 预览切到剩余选中项（或清空），不留死图。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "code128_a.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)  # 选中 qr_hello
    qapp.processEvents()
    assert not win.preview.pixmap().isNull()

    win._remove_item(win.file_list.item(0))  # 移除选中的 qr_hello
    qapp.processEvents()
    assert win.file_list.count() == 1
    pix = win.preview.pixmap()
    assert pix is not None and not pix.isNull(), "剩余项预览应自动恢复"
    win.close()


def test_preview_cleared_when_all_removed(qapp, tmp_path):
    """移除到 0 张 → 预览正常清空。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.file_list.setCurrentRow(0)
    qapp.processEvents()
    win._remove_item(win.file_list.item(0))
    qapp.processEvents()
    assert win.file_list.count() == 0
    assert win.preview.pixmap().isNull()
    win.close()


def test_preview_remove_consistent_in_dedup_view(qapp, tmp_path):
    """去重视图下移除行为一致：移除未选中项不清预览。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "code128_a.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    win.dedup_check.setChecked(True)
    qapp.processEvents()
    win.file_list.setCurrentRow(1)
    qapp.processEvents()
    assert not win.preview.pixmap().isNull()
    win._remove_item(win.file_list.item(0))
    qapp.processEvents()
    assert not win.preview.pixmap().isNull(), "去重视图下移除未选中项误清了预览"
    win.close()
