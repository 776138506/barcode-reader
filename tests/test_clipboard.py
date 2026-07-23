"""剪贴板粘贴测试：offscreen 下给 QClipboard 塞图/塞路径文本模拟粘贴。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
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
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    return mw.MainWindow(settings=settings, **_stores(tmp_path))


def test_paste_clipboard_image(qapp, tmp_path):
    """剪贴板图片数据 → 落盘临时 PNG → 正常解码；不写入会话持久化；退出清理。"""
    win = _make_window(tmp_path)
    clipboard_dir = win._clipboard_dir

    image = QImage(str(IMG_DIR / "qr_hello.png"))
    assert not image.isNull()
    QApplication.clipboard().setImage(image)
    win.paste_from_clipboard()

    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert win.file_list.count() == 1
    assert win.table.rowCount() == 1
    # 内容与码制与原图一致
    assert win.table.item(0, 2).text() == "QRCode"
    assert win.table.item(0, 3).text() == "https://example.com/qr-hello"
    # 临时 PNG 已落盘在会话目录
    pasted = list(clipboard_dir.glob("clipboard_*.png"))
    assert len(pasted) == 1

    # 临时图不进入持久化的最近会话列表
    win._save_settings()
    s = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    recent = s.value(mw.K_RECENT_IMAGES)
    assert not recent or str(pasted[0]) not in (recent if isinstance(recent, list) else [recent])

    # 关闭后临时目录被清理
    win.close()
    assert not clipboard_dir.exists()


def test_paste_file_path_text(qapp, tmp_path):
    """剪贴板是文件路径文本时按 add_paths 流程添加。"""
    win = _make_window(tmp_path)
    QApplication.clipboard().setText(str(IMG_DIR / "code128_a.png"))
    win.paste_from_clipboard()

    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert win.file_list.count() == 1
    assert win.table.rowCount() == 1
    assert win.table.item(0, 2).text() == "Code128"
    win.close()


def test_paste_empty_clipboard_hint(qapp, tmp_path):
    """剪贴板无可用内容时状态栏提示，不崩溃。"""
    win = _make_window(tmp_path)
    QApplication.clipboard().clear()
    win.paste_from_clipboard()
    assert "没有可识别" in win.statusBar().currentMessage()
    assert win.file_list.count() == 0
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}
