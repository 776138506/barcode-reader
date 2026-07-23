"""导出设置对话框：两段式（连接符/外模板/分组）+ 导出过滤（码制/长度/前缀/正则）。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QVBoxLayout, QWidget)

from decoder import FORMAT_WHITELIST
from exporter import DEFAULT_JOINER, DEFAULT_OUTER, ExportFilter
from ui.scroll_helper import cap_dialog_height, wrap_scrollable


class ExportSettingsDialog(QDialog):
    """编辑导出设置。初始值由调用方传入，结果从同名属性读取。"""

    def __init__(self, joiner: str, outer: str, group_by: str,
                 filt: ExportFilter, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出设置")
        self.resize(420, 380)
        content = QWidget(self)
        layout = QVBoxLayout(content)

        # 两段式
        stage_box = QGroupBox("两段式模板")
        form = QFormLayout(stage_box)
        self.joiner_edit = QLineEdit(joiner)
        self.joiner_edit.setToolTip("码与码之间的拼接串，可含引号等任意字符，如 ','")
        form.addRow("连接符:", self.joiner_edit)
        self.outer_edit = QLineEdit(outer)
        self.outer_edit.setToolTip("整体包装，{items} 为必填占位符，其余字符按字面输出")
        form.addRow("外模板:", self.outer_edit)
        self.group_combo = QComboBox()
        self.group_combo.addItem("不分组", "none")
        self.group_combo.addItem("按图片分组", "image")
        self.group_combo.addItem("全局聚合", "global")
        idx = self.group_combo.findData(group_by)
        self.group_combo.setCurrentIndex(max(0, idx))
        form.addRow("分组:", self.group_combo)
        layout.addWidget(stage_box)

        # 过滤
        filter_box = QGroupBox("导出过滤（作用于导出与复制，不影响界面结果）")
        filter_layout = QVBoxLayout(filter_box)
        self.type_boxes: dict[str, QCheckBox] = {}
        grid = QGridLayout()
        for i, name in enumerate(FORMAT_WHITELIST):
            box = QCheckBox(name)
            box.setChecked(filt.types is None or FORMAT_WHITELIST[name] in filt.types)
            self.type_boxes[name] = box
            grid.addWidget(box, i // 3, i % 3)
        filter_layout.addLayout(grid)
        len_row = QHBoxLayout()
        len_row.addWidget(QLabel("内容长度:"))
        self.min_len_edit = QLineEdit("" if filt.min_len is None else str(filt.min_len))
        self.min_len_edit.setPlaceholderText("最小")
        self.min_len_edit.setMaximumWidth(60)
        self.max_len_edit = QLineEdit("" if filt.max_len is None else str(filt.max_len))
        self.max_len_edit.setPlaceholderText("最大")
        self.max_len_edit.setMaximumWidth(60)
        len_row.addWidget(self.min_len_edit)
        len_row.addWidget(QLabel("~"))
        len_row.addWidget(self.max_len_edit)
        len_row.addStretch(1)
        filter_layout.addLayout(len_row)
        fform = QFormLayout()
        self.prefix_edit = QLineEdit(filt.prefix)
        fform.addRow("前缀:", self.prefix_edit)
        self.regex_edit = QLineEdit(filt.regex)
        self.regex_edit.setPlaceholderText("正则（re.search）")
        fform.addRow("正则:", self.regex_edit)
        filter_layout.addLayout(fform)
        layout.addWidget(filter_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        # 小屏幕适配（D21）：内容进滚动区，按钮栏固定在外始终可达
        self._scroll = wrap_scrollable(self, content, buttons)
        cap_dialog_height(self)

    def _on_accept(self):
        """确定前校验长度字段：非数字输入弹警告并留在对话框。"""
        from PySide6.QtWidgets import QMessageBox
        for edit, label in ((self.min_len_edit, "长度最小值"),
                            (self.max_len_edit, "长度最大值")):
            text = edit.text().strip()
            if text:
                try:
                    int(text)
                except ValueError:
                    QMessageBox.warning(self, "导出过滤", f"{label}必须是整数: {text!r}")
                    return
        self.accept()

    # ---- 结果读取 ----

    @property
    def joiner(self) -> str:
        return self.joiner_edit.text() or DEFAULT_JOINER

    @property
    def outer(self) -> str:
        return self.outer_edit.text() or DEFAULT_OUTER

    @property
    def group_by(self) -> str:
        return self.group_combo.currentData()

    def export_filter(self) -> ExportFilter:
        # ExportFilter.types 存 zxing 短名（与 DecodeResult.format 一致），
        # 对话框显示名经 FORMAT_WHITELIST 映射
        types = [FORMAT_WHITELIST[n] for n, b in self.type_boxes.items() if b.isChecked()]
        if len(types) == len(self.type_boxes):
            types = None  # 全选 = 不限制
        return ExportFilter(
            types=types,
            min_len=self._int_or_none(self.min_len_edit.text()),
            max_len=self._int_or_none(self.max_len_edit.text()),
            prefix=self.prefix_edit.text(),
            regex=self.regex_edit.text(),
        )

    @staticmethod
    def _int_or_none(text: str) -> int | None:
        text = text.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
