"""拖放导入测试：MainWindow 级别统一处理，子控件不拦截，QDropEvent 模拟验证。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
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


def _drop(win, mime) -> bool:
    """走完整 dragEnter + drop 链路，返回 dragEnter 是否接受。"""
    pos = QPoint(10, 10)
    enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    win.dragEnterEvent(enter)
    if enter.isAccepted():
        win.dropEvent(QDropEvent(QPointF(pos), Qt.CopyAction, mime,
                                 Qt.LeftButton, Qt.NoModifier))
    return enter.isAccepted()


def test_children_do_not_intercept_drops(qapp, tmp_path):
    """子控件（列表/表格/预览，含 viewport）必须关闭 acceptDrops。"""
    win = _make_window(tmp_path)
    assert win.acceptDrops()  # 主窗口接收
    for w in (win.file_list, win.file_list.viewport(),
              win.table, win.table.viewport(), win.preview):
        assert not w.acceptDrops(), f"{w} 不应拦截拖放"
    win.close()


def test_drop_files_and_folder(qapp, tmp_path):
    """拖入图片文件与文件夹（QDropEvent 模拟）都能导入并去重。"""
    win = _make_window(tmp_path)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(IMG_DIR / "qr_hello.png")),
                  QUrl.fromLocalFile(str(IMG_DIR))])  # 文件夹递归收集（含重复）
    assert _drop(win, mime)
    win._pool.waitForDone(60000)
    qapp.processEvents()
    # 文件夹里 15 张 png（9 普通 + 6 疑难），qr_hello 重复只算一次
    expected = len(list(IMG_DIR.glob("*.png")))
    assert win.file_list.count() == expected
    assert win.table.rowCount() == sum(len(v) for v in win.results.values())
    assert win.table.rowCount() >= expected  # 每张图至少 1 个码
    win.close()


def test_dragenter_rejects_non_urls(qapp, tmp_path):
    """纯文本拖入不接受（ urls 之外的内容走粘贴功能）。"""
    win = _make_window(tmp_path)
    mime = QMimeData()
    mime.setText("hello")
    assert not _drop(win, mime)
    assert win.file_list.count() == 0
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}
