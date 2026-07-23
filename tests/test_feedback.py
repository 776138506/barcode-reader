"""反馈可见性测试：剪贴板导出提示、复制按钮反馈、过滤/校验/操作反馈（任务1+2）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from exporter import ExportFilter  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui.export_settings_dialog import ExportSettingsDialog  # noqa: E402

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


def _add_one(qapp, win):
    win.add_paths([str(IMG_DIR / "qr_hello.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()


# ---------- 任务 1：剪贴板导出提示 ----------

def test_clipboard_copy_success_message(qapp, tmp_path):
    win = _make_window(tmp_path)
    _add_one(qapp, win)
    win.copy_rendered_to_clipboard()
    msg = win.statusBar().currentMessage()
    assert "1 条" in msg and "字符" in msg
    assert QApplication.clipboard().text()
    win.close()


def test_clipboard_copy_zero_records_warns(qapp, tmp_path, monkeypatch):
    win = _make_window(tmp_path)  # 空列表，0 条
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    win.copy_rendered_to_clipboard()
    assert warnings and "没有可导出的记录" in warnings[0][2]
    win.close()


def test_clipboard_copy_regex_error_warns(qapp, tmp_path, monkeypatch):
    win = _make_window(tmp_path)
    _add_one(qapp, win)
    win._filter = ExportFilter(regex="([")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    win.copy_rendered_to_clipboard()
    assert warnings, "正则错误应弹警告"
    win.close()


def test_copy_buttons_feedback(qapp, tmp_path):
    win = _make_window(tmp_path)
    # 0 行选中
    win.copy_selected()
    assert "未选中" in win.statusBar().currentMessage()
    # 0 条记录
    win.copy_all()
    assert "没有可复制" in win.statusBar().currentMessage()
    # 有记录后两个按钮都有条数+字符数
    _add_one(qapp, win)
    win.copy_all()
    assert "1 条" in win.statusBar().currentMessage()
    assert "字符" in win.statusBar().currentMessage()
    win.table.selectAll()
    win.copy_selected()
    assert "字符" in win.statusBar().currentMessage()
    win.close()


# ---------- 任务 2 修复点 ----------

def test_invalid_regex_status_hint(qapp, tmp_path):
    """过滤正则非法：状态栏提示按不过滤处理（原静默吞）。"""
    win = _make_window(tmp_path)
    _add_one(qapp, win)
    win._filter = ExportFilter(regex="([")
    records = win._filtered_records()
    assert len(records) == 1  # 按不过滤处理
    assert "正则无效" in win.statusBar().currentMessage()
    win.close()


def test_open_log_dir_failure_feedback(qapp, tmp_path, monkeypatch):
    win = _make_window(tmp_path)
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda *a, **k: False))
    win.open_log_dir()
    assert "无法打开日志目录" in win.statusBar().currentMessage()
    win.close()


def test_export_settings_invalid_length_warns(qapp, monkeypatch):
    """导出设置长度字段填垃圾：弹警告且不关闭（原静默当无限制）。"""
    d = ExportSettingsDialog("\n", "{items}", "none", ExportFilter())
    d.min_len_edit.setText("abc")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    d._on_accept()
    assert warnings and "整数" in warnings[0][2]
    assert d.result() == 0  # 未接受，留在对话框
    # 合法输入放行
    d.min_len_edit.setText("3")
    d._on_accept()
    assert d.result() != 0
    d.close()


def test_profile_template_ops_feedback(qapp, tmp_path):
    win = _make_window(tmp_path)
    from decoder import DecodeProfile
    win._profiles.save("临时档", DecodeProfile())
    win._reload_profile_combo("临时档")
    win.delete_profile()
    assert "已删除" in win.statusBar().currentMessage()
    win._templates.save("临时模板", win._current_export_config())
    win._reload_tpl_pool_combo("临时模板")
    win.delete_template()
    assert "已删除" in win.statusBar().currentMessage()
    win.close()


def test_profile_dialog_garbage_no_crash(qapp, monkeypatch):
    """profile 编辑输入垃圾值：弹警告不崩溃、不产出结果。"""
    from decoder import DecodeProfile
    from ui.profile_dialog import ProfileDialog
    d = ProfileDialog("测试", DecodeProfile())
    d._edits[("l3", "bands")].setText("abc")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    d._on_accept()
    assert warnings and "无法解析" in warnings[0][2]
    assert d.result() == 0
    d.close()
