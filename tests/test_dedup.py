"""去重视图与 {count} 占位符测试。"""
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from exporter import ExportRecord, render_template  # noqa: E402
from ui import main_window as mw  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"
NOW = datetime(2026, 7, 22, 9, 30, 15)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    return mw.MainWindow(settings=settings, history_db=tmp_path / "history.db", **_stores(tmp_path))


def test_count_placeholder_render():
    r = ExportRecord(filename="a.png;b.png", type="QRCode",
                     content="X", count=2)
    assert render_template("{content}({count})", r, 1, NOW) == "X(2)"
    # 普通记录 count 默认为 1
    r2 = ExportRecord(filename="a.png", type="QRCode", content="Y")
    assert render_template("{count}", r2, 1, NOW) == "1"


def test_dedup_view_and_export(qapp, tmp_path, monkeypatch):
    """两张图含相同码：去重后一行、次数 2、来源两个文件；导出走 {count}。"""
    win = _make_window(tmp_path)
    # qr_hello 与 qr_rotated180 内容相同
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "qr_rotated180.png"),
                   str(IMG_DIR / "code128_a.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert win.table.rowCount() == 3  # 普通视图不变

    win.dedup_check.setChecked(True)
    qapp.processEvents()
    assert win.table.columnCount() == 5
    assert win.table.rowCount() == 2  # 3 条记录去重为 2 个唯一码
    # 找到 QR 那一行
    rows = {win.table.item(i, 3).text(): i for i in range(win.table.rowCount())}
    qr_row = rows["https://example.com/qr-hello"]
    assert win.table.item(qr_row, 1).text() == "2"
    sources = win.table.item(qr_row, 4).text()
    assert "qr_hello.png" in sources and "qr_rotated180.png" in sources

    # 去重模式导出
    win.template_edit.setText("{index},{content},{count}")
    win.format_combo.setCurrentText("CSV")
    out = tmp_path / "dedup.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    win.export_results()
    lines = out.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 3  # 表头 + 2 条唯一码
    assert "1,https://example.com/qr-hello,2" in lines
    assert "2,CODE128-ABC-12345,1" in lines

    # 切回普通视图行为不变
    win.dedup_check.setChecked(False)
    qapp.processEvents()
    assert win.table.columnCount() == 4
    assert win.table.rowCount() == 3
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}
