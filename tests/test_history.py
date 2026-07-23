"""历史记录库（SQLite）测试：写入、搜索、时间排序、失败不阻塞主流程。"""
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from history import History, HistoryRecord  # noqa: E402
from ui import main_window as mw  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _rec(ts, content, filename="a.png", type_="QRCode", src="/tmp/a.png"):
    return HistoryRecord(ts=ts, filename=filename, type=type_,
                         content=content, source_path=src)


def test_history_add_search_order(tmp_path):
    h = History(tmp_path / "history.db")
    h.add_batch([
        _rec("2026-07-20T10:00:00", "HELLO-1"),
        _rec("2026-07-22T09:00:00", "WORLD-2"),
        _rec("2026-07-21T12:00:00", "HELLO-3"),
    ])
    h.add(filename="b.png", type_="Code128", content="CODE-4",
          source_path="/tmp/b.png", ts=datetime(2026, 7, 22, 10, 0, 0))
    assert h.count() == 4

    # 默认按时间倒序
    all_rows = h.search()
    assert [r.content for r in all_rows] == ["CODE-4", "WORLD-2", "HELLO-3", "HELLO-1"]

    # 关键词搜索（内容子串）
    hello = h.search("HELLO")
    assert [r.content for r in hello] == ["HELLO-3", "HELLO-1"]
    assert h.search("不存在的关键词") == []


def test_decode_writes_history(qapp, tmp_path):
    """GUI 解码后历史库自动有记录。"""
    db = tmp_path / "history.db"
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=db, **_stores(tmp_path))
    win.add_paths([str(IMG_DIR / "qr_hello.png"), str(IMG_DIR / "multi_3codes.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()

    h = History(db)
    assert h.count() == 4  # 1 + 3
    rows = h.search("qr-hello")
    assert len(rows) == 2  # qr_hello.png 与 multi_3codes.png 各含一个该码
    single = [r for r in rows if r.filename == "qr_hello.png"]
    assert len(single) == 1
    assert single[0].type == "QRCode"
    assert single[0].source_path.endswith("qr_hello.png")
    win.close()


def test_history_failure_does_not_block(qapp, tmp_path):
    """历史库初始化/写入失败时主流程照常。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")  # 其父路径无法建库
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=blocker / "history.db", **_stores(tmp_path))
    assert win._history is None
    win.add_paths([str(IMG_DIR / "qr_hello.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert win.table.rowCount() == 1  # 解码与表格不受影响
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}
