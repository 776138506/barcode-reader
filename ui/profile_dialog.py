"""识别参数档案编辑对话框：PRE/L1/L2/L3/共识分组全开放编辑 + 恢复默认。"""
from __future__ import annotations

from dataclasses import fields

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from decoder import DecodeProfile
from ui.scroll_helper import cap_dialog_height, wrap_scrollable

# (分组, 字段, 标签, 解析器)
def _ints(text: str) -> list:
    return [int(x) for x in text.replace("，", ",").split(",") if x.strip()]


def _floats(text: str) -> list:
    return [float(x) for x in text.replace("，", ",").split(",") if x.strip()]


def _strs(text: str) -> list:
    return [x.strip() for x in text.replace("，", ",").split(",") if x.strip()]


_FIELD_SPECS = [
    ("PRE 降采样", [
        ("max_pixels", "大图阈值(像素)", int),
        ("downscale_target", "降采样目标(像素)", int),
        ("work_pixels", "L1/L2 工作图上限(像素)", int),
    ]),
    ("L1 增强", [
        ("binarizers", "binarizer 列表(la/gh/ft/bool)", _strs),
        ("clahe_clip", "CLAHE 裁剪上限", float),
        ("clahe_tiles", "CLAHE 分块数", int),
        ("sharpen", "UnsharpMask(半径,百分比,阈值)", _ints),
        ("angles", "细旋转角度集(逗号分隔)", _ints),
        ("upscales", "放大倍率集(逗号分隔)", _floats),
        ("gammas", "gamma 集(逗号分隔)", _floats),
    ]),
    ("L2 组合", [
        ("binarizers", "binarizer 列表", _strs),
        ("enhancers", "增强器列表(clahe/gamma0.6)", _strs),
        ("angles", "旋转角集", _ints),
        ("max_combos", "组合上限", int),
    ]),
    ("L3 区域层", [
        ("bands", "横带数", int),
        ("band_overlap", "横带重叠率", float),
        ("grid", "网格边数", int),
        ("grid_overlap", "网格重叠率", float),
        ("scales", "tile 放大倍率集", _ints),
        ("sharpen", "UnsharpMask(半径,百分比,阈值)", _ints),
        ("angle_min", "旋转角下限", int),
        ("angle_max", "旋转角上限", int),
        ("band_step", "横带角度步进", int),
        ("grid_step", "网格角度步进", int),
        ("binarizers", "binarizer 列表", _strs),
        ("max_combos", "组合上限", int),
    ]),
    ("共识（误识防护）", [
        ("min_signatures", "最小签名数", int),
        ("dist", "聚类中心距(px)", int),
    ]),
]


def _fmt(value) -> str:
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


class ProfileDialog(QDialog):
    """编辑一份 DecodeProfile。初始值由调用方传入；
    结果读 self.profile_name / self.profile。"""

    def __init__(self, name: str, profile: DecodeProfile, parent=None):
        super().__init__(parent)
        self.setWindowTitle("识别参数档案")
        self.resize(520, 640)
        self.profile_name = name
        self.profile = profile

        content = QWidget(self)
        layout = QVBoxLayout(content)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名称:"))
        self.name_edit = QLineEdit(name)
        name_row.addWidget(self.name_edit, stretch=1)
        restore_btn = QPushButton("恢复默认")
        restore_btn.clicked.connect(self._restore_defaults)
        name_row.addWidget(restore_btn)
        layout.addLayout(name_row)

        self._edits: dict[tuple[str, str], QLineEdit] = {}
        data = profile.to_dict()
        for group, specs in _FIELD_SPECS:
            box = QGroupBox(group)
            form = QFormLayout(box)
            for key, label, _parser in specs:
                section_name = self._section_of(group)
                value = data[section_name][key]
                edit = QLineEdit(_fmt(value))
                form.addRow(label + ":", edit)
                self._edits[(section_name, key)] = edit
            layout.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        # 小屏幕适配（D21）：内容进滚动区，按钮栏固定在外始终可达
        self._scroll = wrap_scrollable(self, content, buttons)
        cap_dialog_height(self)

    @staticmethod
    def _section_of(group: str) -> str:
        return {"PRE 降采样": "pre", "L1 增强": "l1", "L2 组合": "l2",
                "L3 区域层": "l3", "共识（误识防护）": "consensus"}[group]

    def _restore_defaults(self):
        data = DecodeProfile().to_dict()
        for (section, key), edit in self._edits.items():
            edit.setText(_fmt(data[section][key]))

    def _on_accept(self):
        data = DecodeProfile().to_dict()
        try:
            for group, specs in _FIELD_SPECS:
                section = self._section_of(group)
                for key, _label, parser in specs:
                    text = self._edits[(section, key)].text().strip()
                    data[section][key] = parser(text)
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "参数错误", f"存在无法解析的参数: {exc}")
            return
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "参数错误", "名称不能为空")
            return
        self.profile_name = name
        self.profile = DecodeProfile.from_dict(data)
        self.accept()
