"""GUI 冒烟测试（offscreen）：创建窗口 → 批量识别测试图 → 校验表格 → 导出校验。

用法: QT_QPA_PLATFORM=offscreen python tests/smoke_gui.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Windows CI 控制台默认 cp1252，中文输出会 UnicodeEncodeError（D41）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.main_window import MainWindow  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}



def simulate_drop(win, paths: list[str]) -> None:
    """用 QMimeData 构造 urls，直接调用 MainWindow 的拖放事件处理函数。"""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    pos = QPoint(10, 10)
    enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    win.dragEnterEvent(enter)
    assert enter.isAccepted(), "dragEnterEvent 应接受含 urls 的拖入"
    drop = QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    win.dropEvent(drop)


def main() -> int:
    app = QApplication([])
    # 注入临时 ini 设置，避免读写真实用户配置
    with tempfile.TemporaryDirectory() as settings_td:
        settings = QSettings(str(Path(settings_td) / "smoke.ini"), QSettings.IniFormat)
        win = MainWindow(settings=settings, **_stores(Path(settings_td)))
        win.show()

        # 模拟拖入：用 QDropEvent 走 MainWindow 拖放链路（含重复添加去重）
        images = sorted(str(p) for p in IMG_DIR.glob("*.png"))
        assert not win.file_list.acceptDrops() and not win.table.acceptDrops(), \
            "子控件应关闭 acceptDrops，拖放由 MainWindow 统一处理"
        simulate_drop(win, images * 3)  # 重复 3 次也应只添加一次
        assert win.file_list.count() == len(images), \
            f"列表应有 {len(images)} 项，实际 {win.file_list.count()}"

        # 等待后台解码完成（CI 慢机上大图/难图可能超过 30s，给足余量）
        win._pool.waitForDone(240000)
        app.processEvents()
        assert win._pending <= 0, f"仍有 {win._pending} 个任务未完成"

        total_rows = win.table.rowCount()
        total_codes = sum(len(v) for v in win.results.values())
        print(f"识别完成: {len(images)} 张图 -> {total_codes} 个码, 表格 {total_rows} 行")
        assert total_rows == total_codes and total_codes > 0
        # multi_3codes.png 应有 3 个码
        multi = str(IMG_DIR / "multi_3codes.png")
        assert len(win.results[multi]) == 3, f"多码图应有 3 个码: {len(win.results[multi])}"

        # 预览与选中联动
        win.file_list.setCurrentRow(0)
        app.processEvents()
        assert win.preview.pixmap() is not None and not win.preview.pixmap().isNull()

        # 模板预览
        win.template_edit.setText("{index}|{type}|{content}")
        app.processEvents()
        assert "QRCode" in win.tpl_preview.text() or "Code128" in win.tpl_preview.text()

        # 导出 TXT + CSV 并校验内容
        from exporter import ExportRecord, export
        records = [ExportRecord(Path(p).name, r.format, r.content)
                   for p, r in win._all_records()]
        with tempfile.TemporaryDirectory() as td:
            txt = Path(td) / "out.txt"
            csvp = Path(td) / "out.csv"
            export(records, txt, "txt", "{index}|{filename}|{type}|{content}")
            export(records, csvp, "csv", "{index},{filename},{type},{content}",
                   header="序号,文件名,码制,内容")
            txt_lines = txt.read_text(encoding="utf-8").splitlines()
            csv_lines = csvp.read_text(encoding="utf-8-sig").splitlines()
            print("TXT 前 2 行:", txt_lines[:2])
            print("CSV 前 2 行:", csv_lines[:2])
            assert len(txt_lines) == len(records)
            assert csv_lines[0] == "序号,文件名,码制,内容"
            assert len(csv_lines) == len(records) + 1

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

