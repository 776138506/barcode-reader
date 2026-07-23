"""状态持久化测试：QSettings 能写回并读回模板/格式/分隔符/最近图片。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

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


def test_settings_roundtrip_after_export(qapp, tmp_path, monkeypatch):
    """导出一次后，QSettings 能读回模板/格式/分隔符/最近图片/导出目录。"""
    win = _make_window(tmp_path)
    win.template_edit.setText("{index},{filename},{type},{content}")
    win.format_combo.setCurrentText("CSV")
    win.delimiter_combo.setCurrentIndex(1)  # Tab

    image = str(IMG_DIR / "qr_hello.png")
    win.add_paths([image])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert win.table.rowCount() == 1

    out = tmp_path / "result.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    win.export_results()
    assert out.exists(), "导出文件应已生成"

    win._save_settings()
    s = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    assert s.value(mw.K_TEMPLATE) == "{index},{filename},{type},{content}"
    assert s.value(mw.K_FORMAT) == "CSV"
    assert s.value(mw.K_DELIMITER) == "\t"
    assert s.value(mw.K_LAST_DIR) == str(tmp_path)
    recent = s.value(mw.K_RECENT_IMAGES)
    assert recent == image or recent == [image]
    # Tab 分隔符应实际生效到导出内容（模板里的逗号列分隔被换成 Tab）
    assert out.read_text(encoding="utf-8-sig").splitlines()[1] == \
        "1\tqr_hello.png\tQRCode\thttps://example.com/qr-hello"
    win.close()


def test_settings_restored_on_next_start(qapp, tmp_path):
    """第二次启动（同一份 ini）能恢复模板与会话图片。"""
    ini = tmp_path / "settings2.ini"
    s = QSettings(str(ini), QSettings.IniFormat)
    image = str(IMG_DIR / "code128_a.png")
    s.setValue(mw.K_TEMPLATE, "{content}")
    s.setValue(mw.K_FORMAT, "TXT")
    s.setValue(mw.K_RECENT_IMAGES, [image, str(tmp_path / "not_exists.png")])
    s.sync()

    win = mw.MainWindow(settings=s, **_stores(tmp_path))
    assert win.template_edit.text() == "{content}"
    assert win.format_combo.currentText() == "TXT"
    # 不存在的路径被过滤，只恢复存在的图片
    assert win.file_list.count() == 1
    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert win.table.rowCount() == 1
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}
