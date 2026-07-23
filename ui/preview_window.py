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
from PySide6.QtWidgets import (QCheckBox, QDialog, QGraphicsItemGroup,
                               QGraphicsPixmapItem, QGraphicsPolygonItem,
                               QGraphicsRectItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

COLOR_VALID = QColor(0, 200, 0)       # 有效码绿框
COLOR_SUSPECT = QColor(230, 200, 0)   # 疑似码黄框
COLOR_HIGHLIGHT = QColor(255, 140, 0) # 点击高亮橙框
DIM_ALPHA = 60                        # 高亮态下其余帧透明度

LABEL_MAX_CHARS = 24  # 标签内容截断阈值（全文在结果表格可见）


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
    """标签文本：`N: 内容`（疑似 `N?: 内容`），内容 >24 字符截断加 …。"""
    text = frame.content
    if len(text) > LABEL_MAX_CHARS:
        text = text[:LABEL_MAX_CHARS] + "…"
    return f"{frame.seq}{'?' if frame.suspect else ''}: {text}"


def label_style(frame: Frame, state: str) -> tuple[QColor, QColor, bool]:
    """标签视觉规范（底色块, 文字色, 是否加粗）：
    - 普通有效：黑底 65%（alpha 165）+ 白字
    - 疑似：深黄底 65% + 白字（标签含 ? 后缀）
    - 高亮：橙底不透明 + 白字加粗
    - dim：底色/文字同步变淡（alpha 40/60）
    """
    if state == "highlight":
        return QColor(255, 140, 0, 255), QColor(255, 255, 255), True
    bg = QColor(150, 125, 0, 165) if frame.suspect else QColor(0, 0, 0, 165)
    text = QColor(255, 255, 255)
    if state == "dim":
        bg = QColor(bg)
        bg.setAlpha(40)
        text = QColor(255, 255, 255, 60)
    return bg, text, False


def label_placement(box_left: float, box_top: float, box_w: float, box_h: float,
                    text_w: float, text_h: float) -> tuple[float, float]:
    """标签底色块左上角位置（水平码专用）：默认紧贴框上方；上方出界（图片顶）则放框内左上。"""
    if box_top - text_h - 2 >= 0:
        return box_left, box_top - text_h - 2
    return box_left + 2, box_top + 2


# ---------------------------------------------------------------- 标签方向（D29）
# zxing 角点约定（已实证，见 DECISIONS.md D29）：TL→TR 是码的阅读方向
# （长边沿条带/码内容方向）。一维码 ±15° 小角度时角点近似轴对齐，
# 由 LABEL_ANGLE_THRESHOLD 内保持水平兜底。

LABEL_ANGLE_THRESHOLD = 5.0  # |角度| 小于此值按水平处理（与旧行为逐一致）


def frame_angle(frame: Frame) -> float:
    """码长边方向角（度，y 向下坐标系，Qt rotate 正方向=顺时针）。

    取 TL→TR 边方向，归一化到 (-90, 90]：文字不倒置（左右/上下读均可读）。
    """
    (x1, y1), (x2, y2) = frame.points[0], frame.points[1]
    angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
    if angle > 90.0:
        angle -= 180.0
    elif angle <= -90.0:
        angle += 180.0
    return angle


def rotated_label_anchor(frame: Frame, angle: float,
                         text_w: float, text_h: float,
                         img_w: float, img_h: float, pad: float = 2.0,
                         ) -> tuple[float, float, float]:
    """旋转标签锚点（用于 translate+rotate 绘制），D30 修正：以绿框几何为准。

    规则：长边 = TL→TR（zxing 阅读方向）；起点 S = 该边沿阅读方向投影
    较小端；标签体贴框外侧（近边距框 pad px），沿阅读方向从 S 延伸；
    标签四角出图片边界时翻到框另一侧。返回 (x, y, angle)：绘制时
    translate(x, y) 后 rotate(angle)，在 (0,0)-(text_w,text_h) 画底与字，
    局部 +x 沿阅读方向、+y 为标签体厚度方向。
    """
    th_ = math.radians(angle)
    e = (math.cos(th_), math.sin(th_))        # 阅读方向（局部 +x）
    m = (-math.sin(th_), math.cos(th_))       # 标签体延伸方向（局部 +y）
    a, b = frame.points[0], frame.points[1]   # TL, TR（长边两端）
    # 起点 S：沿 e 投影较小端（归一化后文本从左/上开始读）
    s = a if a[0] * e[0] + a[1] * e[1] <= b[0] * e[0] + b[1] * e[1] else b
    cx = sum(p[0] for p in frame.points) / 4
    cy = sum(p[1] for p in frame.points) / 4
    # m 指向框外 → 近边 pad 起步；指向框内 → 起点外推 (pad + text_h)
    away = (s[0] - cx) * m[0] + (s[1] - cy) * m[1] > 0

    def _origin(outward: bool) -> tuple[float, float]:
        if outward:
            return s[0] + m[0] * pad, s[1] + m[1] * pad
        return s[0] - m[0] * (pad + text_h), s[1] - m[1] * (pad + text_h)

    x, y = _origin(away)
    corners = [(x + u * e[0] + v * m[0], y + u * e[1] + v * m[1])
               for u in (0.0, text_w) for v in (0.0, text_h)]
    if any(px < 0 or px > img_w or py < 0 or py > img_h for px, py in corners):
        x, y = _origin(not away)  # 出界翻到框另一侧
    return x, y, angle


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

        # 标签：半透明底色块 + 白字（高亮橙底加粗，dim 同步变淡）
        text = frame_label(frame)
        rect = poly.boundingRect()
        font = QFont()
        font.setPixelSize(label_font_size(rect.width(), rect.height()))
        bg_color, text_color, bold = label_style(frame, state)
        font.setBold(bold)
        from PySide6.QtGui import QFontMetricsF
        metrics = QFontMetricsF(font)
        text_w = metrics.horizontalAdvance(text) + 4
        text_h = metrics.height() + 2
        angle = frame_angle(frame)
        if abs(angle) >= LABEL_ANGLE_THRESHOLD:
            # 旋转码：标签沿长边方向排布（组旋转，底色块随文字一起转）
            img_w = self._pix_item.pixmap().width() if self._pix_item else 1e9
            img_h = self._pix_item.pixmap().height() if self._pix_item else 1e9
            ax, ay, angle = rotated_label_anchor(frame, angle, text_w, text_h,
                                                 img_w, img_h)
            group = QGraphicsItemGroup()
            bg_item = QGraphicsRectItem(0, 0, text_w, text_h, group)
            bg_item.setPen(QPen(Qt.NoPen))
            bg_item.setBrush(QBrush(bg_color))
            label = QGraphicsSimpleTextItem(text, group)
            label.setBrush(QBrush(text_color))
            label.setFont(font)
            label.setPos(2, 1)
            group.setPos(ax, ay)
            group.setRotation(angle)
            self._scene.addItem(group)
            visible = self.markers_check.isChecked()
            group.setVisible(visible)
            poly_item.setVisible(visible)
            self._frame_items.append(group)
            return
        lx, ly = label_placement(rect.left(), rect.top(), rect.width(),
                                 rect.height(), text_w, text_h)
        bg_item = self._scene.addRect(lx, ly, text_w, text_h,
                                      QPen(Qt.NoPen), QBrush(bg_color))
        label = QGraphicsSimpleTextItem(text)
        label.setBrush(QBrush(text_color))
        label.setFont(font)
        label.setPos(lx + 2, ly + 1)
        self._scene.addItem(label)  # 必须显式入 scene（addRect 只负责底色块）
        visible = self.markers_check.isChecked()
        for item in (bg_item, label):
            item.setVisible(visible)
            self._frame_items.append(item)
        poly_item.setVisible(visible)

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
