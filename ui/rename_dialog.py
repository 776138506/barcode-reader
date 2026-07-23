"""按码重命名的确认对话框：模板输入 + 旧名→新名预览 + 确认/取消。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from decoder import DecodeResult
from renamer import DEFAULT_RENAME_TEMPLATE, RenamePlan, build_rename_plan


class RenameDialog(QDialog):
    """确认后可通过 self.plan 取最终方案。"""

    def __init__(self, entries: list[tuple[str, list[DecodeResult]]],
                 skip_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("按码重命名")
        self.resize(860, 480)
        self._entries = entries
        self._skip_dir = skip_dir
        self.plan = RenamePlan()

        layout = QVBoxLayout(self)
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(QLabel("文件名模板:"))
        self.template_edit = QLineEdit(DEFAULT_RENAME_TEMPLATE)
        self.template_edit.setToolTip("可用占位符: {content} {index} {type} {filename} {date} {time}")
        self.template_edit.textChanged.connect(self._rebuild)
        tpl_row.addWidget(self.template_edit, stretch=1)
        layout.addLayout(tpl_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["原文件名", "新文件名", "备注"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: gray;")
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("开始重命名")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)

        self._rebuild()

    def _rebuild(self):
        template = self.template_edit.text() or DEFAULT_RENAME_TEMPLATE
        self.plan = build_rename_plan(self._entries, template, self._skip_dir)
        self.table.setRowCount(len(self.plan.items))
        multi = 0
        for row, item in enumerate(self.plan.items):
            self.table.setItem(row, 0, QTableWidgetItem(item.old_path.name))
            notes = []
            if item.skipped:
                self.table.setItem(row, 1, QTableWidgetItem("（跳过）"))
                notes.append(item.skipped)
            else:
                self.table.setItem(row, 1, QTableWidgetItem(item.new_path.name))
                if item.conflict_suffix:
                    notes.append("重名冲突已加序号")
                if item.extra_codes:
                    multi += 1
                    notes.append(f"含 {item.extra_codes + 1} 个码，取第一个")
            self.table.setItem(row, 2, QTableWidgetItem("；".join(notes)))
        skipped = sum(1 for i in self.plan.items if i.skipped)
        self.summary.setText(
            f"将重命名 {len(self.plan.actionable)} 个文件"
            + (f"，跳过 {skipped} 个" if skipped else "")
            + (f"，其中 {multi} 个图含多个码（取第一个）" if multi else ""))
        self._ok_button.setEnabled(bool(self.plan.actionable))
