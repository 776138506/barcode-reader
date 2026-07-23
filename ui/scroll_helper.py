"""对话框小屏幕适配辅助：QScrollArea 包装 + 高度上限（UI 约定，D21）。

内容多的自定义对话框必须用 wrap_scrollable 包装并 cap_dialog_height，
否则小屏幕上底部内容/按钮不可达。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QDialog, QScrollArea

# 对话框最大高度占屏幕可用高度的比例
SCREEN_HEIGHT_RATIO = 0.8


def screen_available_height() -> int:
    """光标所在屏的可用高度（多屏取光标屏，失败回退主屏/800px）。"""
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:
        return 800
    return screen.availableGeometry().height()


def cap_dialog_height(dialog: QDialog, ratio: float = SCREEN_HEIGHT_RATIO) -> int:
    """把对话框最大高度约束为屏幕可用高度 × ratio，返回生效值。"""
    maximum = int(screen_available_height() * ratio)
    dialog.setMaximumHeight(maximum)
    return maximum


def wrap_scrollable(dialog: QDialog, content, buttons) -> QScrollArea:
    """把内容区包进只垂直滚动的 QScrollArea，按钮栏固定在滚动区外始终可达。

    dialog 必须还没有设置主布局；调用后 dialog 布局 = [scroll(内容), buttons]。
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    from PySide6.QtWidgets import QVBoxLayout
    outer = QVBoxLayout(dialog)
    outer.addWidget(scroll, stretch=1)
    outer.addWidget(buttons)
    return scroll
