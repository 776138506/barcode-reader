"""独立预览窗口（F1）+ 标记帧共享模型（F2/F3）。

Frame：一个码的标记帧（四角点、全局序号、是否疑似、内容）。
主预览（PreviewLabel）与本窗口共用 Frame 与配色语义：
- 有效码绿框、疑似码黄框（序号带 ?，与表格浅黄行一致）
- 点击结果行后对应帧橙色加粗、其余帧变淡（F3）
- 序号与结果表格「序号」列一致（跨图累加，F2）

旋转方案（D23）：用 QGraphicsView.rotate 做显示层 90° 步进旋转，
帧（多边形+序号文本）作为 scene item 随视图一起转，框与码的对应关系
天然保持，无需重算坐标；旋转只影响显示，不改文件。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPen, QPixmap,
                           QPolygonF, QTransform)
from PySide6.QtWidgets import (QCheckBox, QDialog, QGraphicsPixmapItem,
                               QGraphicsPolygonItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

COLOR_VALID = QColor(0, 200, 0)       # 有效码绿框
COLOR_SUSPECT = QColor(230, 200, 0)   # 疑似码黄框
COLOR_HIGHLIGHT = QColor(255, 140, 0) # 点击高亮橙框
DIM_ALPHA = 60                        # 高亮态下其余帧透明度


@dataclass
class Frame:
    points: list[tuple[int, int]]
    seq: int
    suspect: bool
    content: str


def build_frames(results: list, seq_start: int = 1) -> list[Frame]:
    """从 DecodeResult 列表构建标记帧，序号从 seq_start 起累加。"""
    frames = []
    for i, r in enumerate(results):
        if len(r.position) == 4:
            frames.append(Frame(points=r.position, seq=seq_start + i,
                                suspect=r.suspect, content=r.content))
    return frames


def frame_state(frame: Frame, highlight_content: str | None) -> str:
    """帧显示状态：highlight（橙）/ dim（变淡）/ normal。"""
    if highlight_content is None:
        return "normal"
    return "highlight" if frame.content == highlight_content else "dim"


def frame_color(frame: Frame, state: str) -> QColor:
    if state == "highlight":
        return COLOR_HIGHLIGHT
    color = COLOR_SUSPECT if frame.suspect else COLOR_VALID
    if state == "dim":
        color = QColor(color)
        color.setAlpha(DIM_ALPHA)
    return color


def frame_label(frame: Frame) -> str:
    return f"{frame.seq}{'?' if frame.suspect else ''}"


def label_font_size(box_w: float, box_h: float) -> int:
    """序号字号随框大小自适应，下限 10 保证小图可读。"""
    return max(10, min(28, int(min(box_w, box_h) * 0.45)))


# ---------------------------------------------------------------- F1 独立预览窗口

class _ZoomView(QGraphicsView):
    """滚轮缩放 + 拖拽平移的 QGraphicsView。"""

    def __init__(self, scene, owner):
        super().__init__(scene, owner)
        self._owner = owner
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    def wheelEvent(self, event):
        self._owner.zoom_by(1.25 if event.angleDelta().y() > 0 else 0.8)


class PreviewWindow(QDialog):
    """独立预览窗口（非模态）：缩放/旋转/平移 + 标记开关 + 高亮跟随。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预览")
        self.resize(900, 700)
        self._rotation = 0
        self._frames: list[Frame] = []
        self._highlight_content: str | None = None
        self._frame_items: list = []
        self._pix_item: QGraphicsPixmapItem | None = None

        bar = QHBoxLayout()
        for text, slot in (("适应窗口", self.fit), ("100%", self.zoom_100),
                           ("放大", self.zoom_in), ("缩小", self.zoom_out),
                           ("左旋", self.rotate_left), ("右旋", self.rotate_right)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        self.markers_check = QCheckBox("显示标记")
        self.markers_check.setChecked(True)
        self.markers_check.toggled.connect(self._on_markers_toggled)
        bar.addWidget(self.markers_check)
        bar.addStretch(1)

        self._scene = QGraphicsScene(self)
        self._view = _ZoomView(self._scene, self)

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self._view, stretch=1)

    # ---- 数据 ----

    def set_image(self, title: str, pixmap: QPixmap, frames: list[Frame],
                  highlight_content: str | None = None):
        """设置图片与标记帧（列表切换时跟随调用）。"""
        self.setWindowTitle(f"预览 - {title}")
        self._frames = frames
        self._highlight_content = highlight_content
        self._scene.clear()
        self._frame_items = []
        self._pix_item = self._scene.addPixmap(pixmap)
        self._rebuild_frame_items()
        self.fit()

    def set_highlight(self, content: str | None):
        self._highlight_content = content
        self._rebuild_frame_items()

    def _rebuild_frame_items(self):
        for item in self._frame_items:
            self._scene.removeItem(item)
        self._frame_items = []
        for frame in self._frames:
            self._add_frame_items(frame)

    def _add_frame_items(self, frame: Frame):
        state = frame_state(frame, self._highlight_content)
        color = frame_color(frame, state)
        width = 4 if state == "highlight" else 3
        poly = QPolygonF([QPointF(x, y) for x, y in frame.points])
        poly_item = QGraphicsPolygonItem(poly)
        poly_item.setPen(QPen(color, width))
        poly_item.setBrush(QBrush(Qt.NoBrush))
        self._scene.addItem(poly_item)
        self._frame_items.append(poly_item)

        label = QGraphicsSimpleTextItem(frame_label(frame))
        rect = poly.boundingRect()
        label.setBrush(QBrush(color))
        font = QFont()
        font.setPixelSize(label_font_size(rect.width(), rect.height()))
        label.setFont(font)
        text_w = label.boundingRect().width()
        # 框内放得下就放框内左上，否则放框外上方（F2 小框可读性）
        if rect.width() >= text_w + 4:
            label.setPos(rect.left() + 2, rect.top() + 2)
        else:
            label.setPos(rect.left(), rect.top() - label.boundingRect().height() - 2)
        label.setVisible(self.markers_check.isChecked())
        poly_item.setVisible(self.markers_check.isChecked())
        self._scene.addItem(label)
        self._frame_items.append(label)

    # ---- 视图操作 ----

    def _current_scale(self) -> float:
        t = self._view.transform()
        return math.hypot(t.m11(), t.m12())

    def _apply(self, scale: float):
        self._view.setTransform(QTransform().rotate(self._rotation).scale(scale, scale))

    def fit(self):
        if self._pix_item is not None:
            self._view.fitInView(self._pix_item, Qt.KeepAspectRatio)

    def zoom_100(self):
        self._apply(1.0)

    def zoom_by(self, factor: float):
        self._apply(self._current_scale() * factor)

    def zoom_in(self):
        self.zoom_by(1.25)

    def zoom_out(self):
        self.zoom_by(0.8)

    def rotate_left(self):
        self._rotation -= 90
        self._apply(self._current_scale())

    def rotate_right(self):
        self._rotation += 90
        self._apply(self._current_scale())

    def _on_markers_toggled(self, checked: bool):
        for item in self._frame_items:
            item.setVisible(checked)
