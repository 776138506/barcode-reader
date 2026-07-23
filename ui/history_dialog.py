"""历史记录对话框：关键词搜索、时间倒序、载入结果表格、复制内容。"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from history import History, HistoryRecord

logger = logging.getLogger(__name__)


class HistoryDialog(QDialog):
    def __init__(self, history: History, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史记录")
        self.resize(860, 480)
        self._history = history
        self._records: list[HistoryRecord] = []

        layout = QVBoxLayout(self)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("关键词:"))
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("按码内容搜索，留空显示全部")
        self.keyword_edit.returnPressed.connect(self.refresh)
        search_row.addWidget(self.keyword_edit, stretch=1)
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self.refresh)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["时间", "文件名", "码制", "内容", "来源路径"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("载入选中到结果")
        load_btn.clicked.connect(self.load_selected)
        copy_btn = QPushButton("复制选中内容")
        copy_btn.clicked.connect(self.copy_selected)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self):
        try:
            self._records = self._history.search(self.keyword_edit.text().strip())
        except Exception:  # noqa: BLE001
            logger.exception("历史记录查询失败")
            self._records = []
            QMessageBox.warning(self, "历史记录", "查询失败，详情见日志")
        self.table.setRowCount(len(self._records))
        for row, r in enumerate(self._records):
            self.table.setItem(row, 0, QTableWidgetItem(r.ts))
            self.table.setItem(row, 1, QTableWidgetItem(r.filename))
            self.table.setItem(row, 2, QTableWidgetItem(r.type))
            self.table.setItem(row, 3, QTableWidgetItem(r.content))
            self.table.setItem(row, 4, QTableWidgetItem(r.source_path))

    def _selected_records(self) -> list[HistoryRecord]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._records[r] for r in rows]

    def load_selected(self):
        """把选中记录的来源图片重新载入主窗口结果表格（重新解码）。"""
        selected = self._selected_records()
        if not selected:
            return
        existing = sorted({r.source_path for r in selected if Path(r.source_path).is_file()})
        missing = len(selected) - len(existing)
        parent = self.parent()
        if existing and hasattr(parent, "add_paths"):
            parent.add_paths(existing)
        if missing:
            QMessageBox.information(
                self, "载入", f"{missing} 条记录的源文件已不存在，仅载入 {len(existing)} 个")
        if existing:
            self.accept()

    def copy_selected(self):
        selected = self._selected_records()
        if selected:
            QApplication.clipboard().setText("\n".join(r.content for r in selected))
