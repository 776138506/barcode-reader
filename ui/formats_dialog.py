"""码制白名单对话框：勾选允许识别的码制（默认全选）。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGridLayout,
                               QVBoxLayout)

from decoder import FORMAT_WHITELIST


class FormatsDialog(QDialog):
    def __init__(self, selected: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("码制白名单")
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self._boxes: dict[str, QCheckBox] = {}
        for i, name in enumerate(FORMAT_WHITELIST):
            box = QCheckBox(name)
            box.setChecked(name in selected)
            self._boxes[name] = box
            grid.addWidget(box, i // 2, i % 2)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> list[str]:
        return [name for name, box in self._boxes.items() if box.isChecked()]
