"""对话框小屏幕适配测试（D21）：滚动区存在、高度上限生效、内容完整可达。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QGroupBox, QScrollArea  # noqa: E402

from decoder import DecodeProfile  # noqa: E402
from exporter import ExportFilter  # noqa: E402
from ui.profile_dialog import ProfileDialog  # noqa: E402
from ui.export_settings_dialog import ExportSettingsDialog  # noqa: E402
from ui.scroll_helper import SCREEN_HEIGHT_RATIO, screen_available_height  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _assert_scroll_adapted(dialog, group_titles):
    # 1. QScrollArea 存在且 widgetResizable
    scrolls = dialog.findChildren(QScrollArea)
    assert len(scrolls) == 1
    scroll = scrolls[0]
    assert scroll.widgetResizable()
    # 2. 高度上限 = 屏幕可用高度 × 比例（offscreen 800 → 640）
    expected = int(screen_available_height() * SCREEN_HEIGHT_RATIO)
    assert dialog.maximumHeight() == expected
    # 3. 全部内容在滚动区内（小屏幕可滚动访问）
    content = scroll.widget()
    found = {box.title() for box in content.findChildren(QGroupBox)}
    assert found == set(group_titles)
    # 4. 按钮栏在滚动区外（始终可达）
    bbox = dialog.findChild(QDialogButtonBox)
    assert bbox is not None and bbox.parentWidget() is dialog


def test_profile_dialog_scrollable(qapp):
    d = ProfileDialog("默认", DecodeProfile())
    _assert_scroll_adapted(d, ["PRE 降采样", "L1 增强", "L2 组合", "L3 区域层",
                               "共识（误识防护）"])
    # 修复前 sizeHint 高 1104px（offscreen），修复后对话框实际高度不超上限
    d.show()
    qapp.processEvents()
    assert d.height() <= d.maximumHeight()
    # 内容原始高度仍超过上限 → 滚动条策略生效（可滚动到底部）
    scroll = d.findChildren(QScrollArea)[0]
    assert scroll.widget().sizeHint().height() > d.maximumHeight()
    d.close()


def test_export_settings_dialog_scrollable(qapp):
    d = ExportSettingsDialog("\n", "{items}", "none", ExportFilter())
    _assert_scroll_adapted(d, ["两段式模板", "导出过滤（作用于导出与复制，不影响界面结果）"])
    d.close()


def test_cap_follows_screen(qapp, monkeypatch):
    """小屏（mock 可用高度 500）时上限按比例缩小，内容仍可完整访问。"""
    monkeypatch.setattr("ui.scroll_helper.screen_available_height", lambda: 500)
    from ui.scroll_helper import cap_dialog_height
    d = ProfileDialog("默认", DecodeProfile())
    # 重新按小屏应用上限（构造时已按真实屏设置过，这里验证来源逻辑）
    assert cap_dialog_height(d) == int(500 * SCREEN_HEIGHT_RATIO)
    assert d.maximumHeight() == 400
    d.close()
