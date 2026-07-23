"""健壮性改进测试：JSON 损坏保护（备份+提示+回落）、写库失败、批量失败汇总。"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from decoder import DecodeProfile  # noqa: E402
from profiles import BUILTIN_NAME, ProfileStore  # noqa: E402
from templates import BUILTIN_TEMPLATES, TemplateStore  # noqa: E402
from ui import main_window as mw  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(tmp_path, **kwargs):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    kwargs.setdefault("profile_store", ProfileStore(tmp_path / "profiles.json"))
    kwargs.setdefault("template_store", TemplateStore(tmp_path / "templates.json"))
    return mw.MainWindow(settings=settings, history_db=tmp_path / "h.db", **kwargs)


# ---------- 任务 1：JSON 损坏保护 ----------

def test_profiles_corrupt_backup_and_fallback(tmp_path):
    p = tmp_path / "profiles.json"
    p.write_text("{损坏的JSON", encoding="utf-8")
    store = ProfileStore(p)
    # ① 备份生成且内容保留
    backups = list(tmp_path.glob("profiles.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{损坏的JSON"
    # 原文件未被覆盖
    assert p.read_text(encoding="utf-8") == "{损坏的JSON"
    # ② 备份路径暴露给 UI 提示
    assert store.corrupt_backup == backups[0]
    # ③ 回落默认可用
    assert store.names() == [BUILTIN_NAME]
    assert store.get(BUILTIN_NAME).to_dict() == DecodeProfile().to_dict()


def test_templates_corrupt_backup_and_presets(tmp_path):
    p = tmp_path / "templates.json"
    p.write_text("not json at all", encoding="utf-8")
    store = TemplateStore(p)
    backups = list(tmp_path.glob("templates.json.corrupt-*.bak"))
    assert len(backups) == 1 and store.corrupt_backup == backups[0]
    # 内置预设不受影响（重新生成且可写）
    for name in BUILTIN_TEMPLATES:
        assert store.get(name) is not None
    assert json.loads(p.read_text(encoding="utf-8"))  # 重写为合法 JSON


def test_store_write_failure_raises_friendly(tmp_path, monkeypatch):
    """写库失败（只读目录等）：记日志并抛 ValueError 供 UI 弹窗（不再直达崩溃）。"""
    store = ProfileStore(tmp_path / "profiles.json")

    def boom(*a, **k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(ValueError, match="写入失败"):
        store.save("x", DecodeProfile())


def test_gui_corrupt_prompt_once(qapp, tmp_path, monkeypatch):
    """启动时损坏提示：一次性弹窗 + 状态栏（D25）。"""
    (tmp_path / "profiles.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "templates.json").write_text("[bad", encoding="utf-8")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    win = _make_window(tmp_path)
    assert len(warnings) == 1
    assert "配置文件损坏" in warnings[0][1] and ".bak" in warnings[0][2]
    assert "回落默认" in win.statusBar().currentMessage() or \
        "配置文件损坏" in win.statusBar().currentMessage()
    win.close()


# ---------- 任务 2：批量失败汇总 ----------

def test_batch_summary_with_failures(qapp, tmp_path):
    win = _make_window(tmp_path)
    bad = tmp_path / "broken.png"
    bad.write_text("这不是图片", encoding="utf-8")
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(bad)])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    msg = win.statusBar().currentMessage()
    assert "成功 1 张" in msg and "失败 1 张" in msg
    assert len(win.errors) == 1
    win.close()


def test_batch_summary_all_success_no_warning(qapp, tmp_path):
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "code128_a.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    msg = win.statusBar().currentMessage()
    assert "失败" not in msg
    assert "2 张图" in msg
    win.close()
