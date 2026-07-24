"""worker 生命周期竞态回归测试（D37）：窗口在解码进行中 close+GC 不应崩。"""
import contextlib
import gc
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings, QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402
from ui import main_window as mw  # noqa: E402

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


def test_worker_registry_lifecycle(qapp, tmp_path):
    """注册表机制：解码进行中注册非空、完成后清空。"""
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "hard_big.png")])  # 大图解码较慢，注册表应非空
    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert not mw._ACTIVE_WORKERS, "完成后注册表应清空"
    win.close()


def test_worker_survives_window_close_and_gc(qapp, tmp_path):
    """竞态回归：解码进行中 close 窗口并 GC——worker 不被误删、无 RuntimeError。

    修复前（self._workers 挂在窗口上）：窗口 GC 后 worker signals 被删，
    emit 抛 RuntimeError（stderr 出现 "Signal source has been deleted"），
    finished 信号丢失。
    """
    win = _make_window(tmp_path)
    win.add_paths([str(IMG_DIR / "hard_big.png")])
    assert win._pending >= 1, "应有进行中的解码任务"
    win.close()
    del win  # 窗口立即失引用；CPython 引用计数会立刻回收（含其 _workers 集合）
    gc.collect()

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        QThreadPool.globalInstance().waitForDone(30000)
        qapp.processEvents()
    assert "Signal source has been deleted" not in stderr.getvalue(), \
        f"worker 被误删导致 emit 崩溃: {stderr.getvalue()[:500]}"
    assert not mw._ACTIVE_WORKERS, "worker 应正常完成并注销"


def test_rebuilt_window_after_close(qapp, tmp_path):
    """关闭后重建窗口：旧 worker 完成不影响新窗口（不错乱）。"""
    win1 = _make_window(tmp_path / "w1")
    win1.add_paths([str(IMG_DIR / "hard_big.png")])
    win1.close()
    win2 = _make_window(tmp_path / "w2")
    win2.add_paths([str(IMG_DIR / "qr_hello.png")])
    win2._pool.waitForDone(30000)
    qapp.processEvents()
    QThreadPool.globalInstance().waitForDone(30000)
    qapp.processEvents()
    # 新窗口结果不受旧 worker 影响
    assert len(win2.results) == 1
    assert not mw._ACTIVE_WORKERS
    win2.close()


RACE_REPRO_SCRIPT = '''
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, {project_root!r})
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from profiles import ProfileStore
from templates import TemplateStore
from ui.main_window import MainWindow
import tempfile
from pathlib import Path

td = tempfile.mkdtemp()
app = QApplication([])
win = MainWindow(
    settings=QSettings(str(Path(td) / "s.ini"), QSettings.IniFormat),
    history_db=Path(td) / "h.db",
    profile_store=ProfileStore(Path(td) / "p.json"),
    template_store=TemplateStore(Path(td) / "t.json"))
win.add_paths([{image!r}])
sys.exit(1)  # 不等待解码完成直接退出：atexit 应兜底等 worker 收尾
'''


def test_interpreter_exit_with_running_worker(qapp):
    """CI smoke 竞态复现（D41）：解码进行中解释器退出，atexit 兜底后
    stderr 不得出现 "Signal source has been deleted"。"""
    import subprocess
    project_root = str(Path(__file__).resolve().parent.parent)
    script = RACE_REPRO_SCRIPT.format(
        project_root=project_root,
        image=str(IMG_DIR / "hard_big.png"))
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120)
    assert "Signal source has been deleted" not in proc.stderr, \
        f"解释器退出时 worker emit 崩溃: {proc.stderr[:500]}"
