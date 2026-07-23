"""按码重命名测试：非法字符、重名冲突、一图多码、剪贴板临时图跳过、GUI 状态同步。"""
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import zxingcpp  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from decoder import decode_image  # noqa: E402
from renamer import (build_rename_plan, execute_rename,  # noqa: E402
                     sanitize_filename)
from ui import main_window as mw  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_qr(content: str, path: Path):
    b = zxingcpp.create_barcode(content, zxingcpp.BarcodeFormat.QRCode)
    img = Image.fromarray(np.array(b.to_image()))
    w, h = img.size
    img = img.resize((w * 3, h * 3), Image.NEAREST)
    img.save(path)
    return path


def _entries(paths):
    return [(str(p), decode_image(p)) for p in paths]


def test_sanitize_illegal_chars():
    assert sanitize_filename('A/B\\C:D*E?F"G<H>I|J') == "A_B_C_D_E_F_G_H_I_J"
    assert sanitize_filename("  name. ") == "name"
    assert sanitize_filename("...") == "unnamed"


def test_plan_illegal_chars_and_conflict(tmp_path):
    p1 = _make_qr("A/B:C", tmp_path / "x1.png")
    p2 = _make_qr("A/B:C", tmp_path / "x2.png")  # 相同内容 → 冲突加序号
    plan = build_rename_plan(_entries([p1, p2]), "{content}")
    assert plan.items[0].new_path.name == "A_B_C.png"
    assert plan.items[1].new_path.name == "A_B_C_2.png"
    assert plan.items[1].conflict_suffix

    ok, failures = execute_rename(plan)
    assert ok == 2 and not failures
    assert (tmp_path / "A_B_C.png").exists()
    assert (tmp_path / "A_B_C_2.png").exists()
    assert not p1.exists() and not p2.exists()


def test_plan_multi_code_uses_first(tmp_path):
    src = IMG_DIR / "multi_3codes.png"
    dst = tmp_path / "multi.png"
    shutil.copy(src, dst)
    plan = build_rename_plan(_entries([dst]), "{type}_{content}")
    item = plan.items[0]
    assert item.extra_codes == 2  # 共 3 个码，取第一个
    assert item.new_path.name == "QRCode_https___example.com_qr-hello.png"


def test_plan_skip_clipboard_dir(tmp_path):
    clip = tmp_path / "clip"
    clip.mkdir()
    p = _make_qr("TEMP", clip / "clipboard_001.png")
    plan = build_rename_plan(_entries([p]), "{content}", skip_dir=clip)
    assert plan.items[0].skipped
    assert not plan.actionable


def test_rename_updates_gui_state(qapp, tmp_path, monkeypatch):
    """重命名后文件列表/结果表格/QSettings 会话路径同步更新。"""
    src = IMG_DIR / "qr_hello.png"
    dst = tmp_path / "old name.png"
    shutil.copy(src, dst)

    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=tmp_path / "h.db", **_stores(tmp_path))
    win.add_paths([str(dst)])
    win._pool.waitForDone(30000)
    qapp.processEvents()

    # 伪造对话框：直接确认，模板 {content}
    class FakeDialog:
        def __init__(self, entries, skip_dir=None, parent=None):
            self.plan = build_rename_plan(entries, "{content}", skip_dir)

        def exec(self):
            return True

    monkeypatch.setattr(mw, "RenameDialog", FakeDialog)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    win.rename_by_code()

    new_path = tmp_path / "https___example.com_qr-hello.png"
    assert new_path.exists() and not dst.exists()
    item_path = win.file_list.item(0).data(0x0100)  # Qt.UserRole
    assert item_path == str(new_path)
    assert str(new_path) in win.results
    assert win.table.item(0, 1).text() == new_path.name
    # QSettings 会话列表已同步
    recent = settings.value(mw.K_RECENT_IMAGES)
    recent = recent if isinstance(recent, list) else [recent]
    assert str(new_path) in recent and str(dst) not in recent
    win.close()


def test_rename_skips_clipboard_image_in_gui(qapp, tmp_path, monkeypatch):
    """粘贴的临时图在重命名中被跳过且文件保持不动。"""
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=tmp_path / "h.db", **_stores(tmp_path))
    QApplication.clipboard().setImage(QImage(str(IMG_DIR / "qr_hello.png")))
    win.paste_from_clipboard()
    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert win.file_list.count() == 1
    pasted = win.file_list.item(0).data(0x0100)

    class FakeDialog:
        def __init__(self, entries, skip_dir=None, parent=None):
            self.plan = build_rename_plan(entries, "{content}", skip_dir)

        def exec(self):
            return True

    monkeypatch.setattr(mw, "RenameDialog", FakeDialog)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    win.rename_by_code()
    assert Path(pasted).exists()  # 未被重命名/移动
    assert win.file_list.item(0).data(0x0100) == pasted
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}
