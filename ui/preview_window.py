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
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter,  # noqa: E402
                           QPen, QPixmap, QPolygonF, QTransform)
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


def frame_long_edge(frame: Frame) -> float:
    """绿框长边长度（沿阅读方向的可用标签长度，D35 等长省略的目标）。"""
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = frame.points
    e1 = math.hypot(x2 - x1, y2 - y1)
    e2 = math.hypot(x3 - x2, y3 - y2)
    return max(e1, e2)


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

    取 TL→TR 与 TR→BR 中较长的一条边作为长边方向（D29 实证 TL→TR 通常是
    阅读方向；但部分平台 zxing 对旋转码返回轴对齐角点，此时 TL→TR 是短边，
    竖排码会被误判为水平——D38 修正为取长边），归一化到 (-90, 90] 使文字
    不倒置（左右/上下读均可读）。
    """
    (x1, y1), (x2, y2), (x3, y3), _ = frame.points
    dx1, dy1 = x2 - x1, y2 - y1
    dx2, dy2 = x3 - x2, y3 - y2
    if dx1 * dx1 + dy1 * dy1 >= dx2 * dx2 + dy2 * dy2:
        dx, dy = dx1, dy1
    else:
        dx, dy = dx2, dy2
    angle = math.degrees(math.atan2(dy, dx))
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
    # 翻转后仍出界（图顶/图左等单翻盖不住的方向）→ 平移收进界内（D39）
    corners = [(x + u * e[0] + v * m[0], y + u * e[1] + v * m[1])
               for u in (0.0, text_w) for v in (0.0, text_h)]
    min_x = min(c[0] for c in corners)
    max_x = max(c[0] for c in corners)
    min_y = min(c[1] for c in corners)
    max_y = max(c[1] for c in corners)
    dx = (-min_x) if min_x < 0 else (img_w - max_x if max_x > img_w else 0.0)
    dy = (-min_y) if min_y < 0 else (img_h - max_y if max_y > img_h else 0.0)
    return x + dx, y + dy, angle


# ---------------------------------------------------------------- 标签降级（D31）

MIN_FONT_PX = 10.0  # 可读阈值：有效字高低于此值降级为徽标


@dataclass
class LabelLayout:
    """单个标签的绘制布局（plan_label 产出）。"""
    mode: str          # "full" 全长标签 | "badge" 紧凑徽标
    text: str          # full: "N: 内容" / badge: "N" 或 "N?"
    x: float
    y: float
    w: float
    h: float
    angle: float = 0.0


def _rect_of(layout: LabelLayout) -> tuple[float, float, float, float]:
    """布局的世界轴对齐矩形（旋转标签取四角 AABB，用于碰撞检测）。"""
    if layout.angle == 0.0:
        return (layout.x, layout.y, layout.x + layout.w, layout.y + layout.h)
    t = math.radians(layout.angle)
    e = (math.cos(t), math.sin(t))
    m = (-math.sin(t), math.cos(t))
    corners = [(layout.x + u * e[0] + v * m[0], layout.y + u * e[1] + v * m[1])
               for u in (0.0, layout.w) for v in (0.0, layout.h)]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _rects_collide(a, b) -> bool:
    """矩形格式统一为 (x0, y0, x1, y1)。"""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def elide_label(frame: Frame, font, target_w: float) -> str | None:
    """中间省略的自适应标签（D35）：目标宽度 = 绿框长边。

    - 全长 `N: 内容`（疑似 `N?: 内容`）渲染宽 ≤ target_w → 原样返回
    - 否则内容中间省略为 `前k…后k`，k 从 max((len-1)//2, 1) 起每级减 2，
      最短形式 `N: a…b`（k=1）
    - 序号永不省略；最短形式仍超 target_w → 返回 None（调用方降级徽标）
    宽度一律用传入 font 的 QFontMetricsF 实测（不硬编码字符数，D34 教训）。
    """
    from PySide6.QtGui import QFontMetricsF
    metrics = QFontMetricsF(font)
    full = frame_label(frame)
    if metrics.horizontalAdvance(full) + 4 <= target_w:
        return full
    prefix = f"{frame.seq}{'?' if frame.suspect else ''}: "
    content = frame.content
    max_k = max((len(content) - 1) // 2, 1)
    k = max_k
    while k >= 1:
        text = f"{prefix}{content[:k]}…{content[-k:]}"
        if metrics.horizontalAdvance(text) + 4 <= target_w:
            return text
        k -= 2
    # 步进可能跳过 k=1（max_k 为偶数时），最短形式兜底再试
    text = f"{prefix}{content[:1]}…{content[-1:]}"
    if metrics.horizontalAdvance(text) + 4 <= target_w:
        return text
    return None


def _badge_layout(frame: Frame, metrics) -> "LabelLayout":
    """紧凑徽标布局：锚在框角内侧（左上）。"""
    xs = [p[0] for p in frame.points]
    ys = [p[1] for p in frame.points]
    text = f"{frame.seq}{'?' if frame.suspect else ''}"
    return LabelLayout(mode="badge", text=text,
                       x=min(xs) + 2, y=min(ys) + 2,
                       w=metrics.horizontalAdvance(text) + 6,
                       h=metrics.height() + 2, angle=0.0)


def _full_label_layout(frame: Frame, font,
                       img_w: float, img_h: float,
                       pad: float = 2.0) -> LabelLayout:
    """F1（交互模式）专用：标签永远全长（D39）。

    不省略、不降级徽标、不做碰撞处理（用户可缩放平移查看）；
    锚定规则与主预览一致（水平贴框上方、旋转沿长边贴框），
    出图片边界时翻转/平移收进界内保证完整可见。
    """
    from PySide6.QtGui import QFontMetricsF
    metrics = QFontMetricsF(font)
    text = frame_label(frame)
    text_w = metrics.horizontalAdvance(text) + 4
    text_h = metrics.height() + 2
    angle = frame_angle(frame)
    if abs(angle) < LABEL_ANGLE_THRESHOLD:
        xs = [p[0] for p in frame.points]
        ys = [p[1] for p in frame.points]
        box_w = max(xs) - min(xs)
        box_h = max(ys) - min(ys)
        lx, ly = label_placement(min(xs), min(ys), box_w, box_h, text_w, text_h)
        if text_w <= img_w:
            lx = min(max(lx, 0.0), img_w - text_w)
        else:
            lx = 0.0
        ly = min(max(ly, 0.0), max(0.0, img_h - text_h))
        return LabelLayout(mode="full", text=text,
                           x=lx, y=ly, w=text_w, h=text_h, angle=0.0)
    ax, ay, angle = rotated_label_anchor(frame, angle, text_w, text_h,
                                         img_w, img_h, pad)
    return LabelLayout(mode="full", text=text,
                       x=ax, y=ay, w=text_w, h=text_h, angle=angle)


def plan_label(frame: Frame, font,
               img_w: float, img_h: float,
               placed: list, pad: float = 2.0) -> LabelLayout:
    """计算标签布局（D31/D33 降级 + D35 等长省略）。

    文本生成（省略在碰撞判定之前）：
    - 目标宽度 = 绿框长边（frame_long_edge）；全长 `N: 内容` 渲染宽 ≤ 目标
      → 原样；超过 → 中间省略 `前k…后k`（elide_label，序号永不省略）；
      最短形式仍超 → 直接降级徽标。
    布局与降级（D33 规则不变）：
    - 水平码（<5°）：锚定框上方，标签平移收进图片边界（次级兜底）；
      旋转码：D30 frame-relative 锚定沿长边贴框。
    - 与已绘制标签碰撞 → 降级徽标（先画保留全长，后冲突降级）；
      渲染矩形出图片边界 → 降级徽标。

    placed 为本轮已确认的全长标签矩形（就地追加）。
    """
    from PySide6.QtGui import QFontMetricsF
    metrics = QFontMetricsF(font)
    angle = frame_angle(frame)
    text = elide_label(frame, font, frame_long_edge(frame))
    if text is None:
        return _badge_layout(frame, metrics)
    text_w = metrics.horizontalAdvance(text) + 4
    text_h = metrics.height() + 2
    if abs(angle) < LABEL_ANGLE_THRESHOLD:
        xs = [p[0] for p in frame.points]
        ys = [p[1] for p in frame.points]
        box_w = max(xs) - min(xs)
        box_h = max(ys) - min(ys)
        lx, ly = label_placement(min(xs), min(ys), box_w, box_h, text_w, text_h)
        # 水平标签平移收进图片边界（次级兜底）
        if text_w <= img_w:
            lx = min(max(lx, 0.0), img_w - text_w)
        else:
            lx = 0.0
        ly = min(max(ly, 0.0), max(0.0, img_h - text_h))
        layout = LabelLayout(mode="full", text=text,
                             x=lx, y=ly, w=text_w, h=text_h, angle=0.0)
    else:
        ax, ay, angle = rotated_label_anchor(frame, angle, text_w, text_h,
                                             img_w, img_h, pad)
        layout = LabelLayout(mode="full", text=text,
                             x=ax, y=ay, w=text_w, h=text_h, angle=angle)

    rect = _rect_of(layout)
    out_of_bounds = (rect[0] < 0 or rect[2] > img_w
                     or rect[1] < 0 or rect[3] > img_h)
    collide = any(_rects_collide(rect, r) for r in placed)
    if not out_of_bounds and not collide:
        placed.append(rect)
        return layout
    return _badge_layout(frame, metrics)


def label_font_size(box_w: float, box_h: float) -> int:
    """序号字号随框大小自适应，下限 10 保证小图可读。"""
    return max(10, min(28, int(min(box_w, box_h) * 0.45)))


# ---------------------------------------------------------------- 统一预览组件（D32）

class PreviewView(QGraphicsView):
    """统一预览组件：主预览（嵌入模式）与 F1 独立窗口共用渲染。

    - Frame 标记四态样式 + plan_label 自适应降级（碰撞/出界/字高不足 → 徽标）
    - 嵌入模式（interactive=False，主预览）：适应窗口、无滚动条、无缩放平移
      交互，保留单击（清高亮）/双击（on_double_click）回调
    - F1 模式（interactive=True）：滚轮缩放、拖拽平移、90° 步进旋转
    - 缩放/尺寸变化实时重算降级布局
    """

    def __init__(self, parent=None, interactive: bool = False):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setFrameShape(QGraphicsView.NoFrame)
        self._interactive = interactive
        self._frames: list[Frame] = []
        self._highlight_content: str | None = None
        self._pix_item: QGraphicsPixmapItem | None = None
        self._frame_items: list = []
        self._message_item = None
        self._rotation = 0
        self._markers_visible = True
        self.on_blank_click = None
        self.on_double_click = None
        # 拖放纪律（D07）：组件与 viewport 一律不拦截
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)
        if interactive:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        else:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    # ---- 数据 ----

    def set_image(self, pixmap: QPixmap, frames: list[Frame]):
        self._scene.clear()
        self._frames = frames
        self._frame_items = []
        self._message_item = None
        self._pix_item = self._scene.addPixmap(pixmap)
        self._rebuild()
        self.fit()

    def set_frames(self, frames: list[Frame]):
        self._frames = frames
        self._rebuild()

    def set_highlight(self, content: str | None):
        self._highlight_content = content
        self._rebuild()

    def set_message(self, text: str):
        """占位提示（加载失败/空态）。"""
        self._scene.clear()
        self._frames = []
        self._frame_items = []
        self._pix_item = None
        self._message_item = self._scene.addText(text)
        self.fit()

    def message(self) -> str:
        return self._message_item.toPlainText() if self._message_item else ""

    def clear_image(self):
        self._frames = []
        self._highlight_content = None
        self.set_message("预览区")

    def set_markers_visible(self, visible: bool):
        self._markers_visible = visible
        for item in self._frame_items:
            item.setVisible(visible)

    # 兼容旧 PreviewLabel 测试接口
    def pixmap(self) -> QPixmap:
        """无图（空态/加载失败）时返回空 QPixmap；有图时返回当前渲染视图。"""
        if self._pix_item is None:
            return QPixmap()
        return self.grab()

    def text(self) -> str:
        return self.message()

    # ---- 渲染 ----

    def _effective_font_scale(self) -> float:
        t = self.transform()
        s = math.hypot(t.m11(), t.m12())
        return s if s > 0 else 1.0

    def _rebuild(self):
        for item in list(self._frame_items):
            self._scene.removeItem(item)
        self._frame_items = []
        if self._pix_item is None:
            return
        img_w = self._pix_item.pixmap().width()
        img_h = self._pix_item.pixmap().height()
        placed: list = []
        for frame in self._frames:
            self._add_frame(frame, img_w, img_h, placed)

    def _add_frame(self, frame: Frame, img_w: float, img_h: float, placed: list):
        state = frame_state(frame, self._highlight_content)
        color = frame_color(frame, state)
        poly = QPolygonF([QPointF(x, y) for x, y in frame.points])
        poly_item = QGraphicsPolygonItem(poly)
        poly_item.setPen(QPen(color, 4 if state == "highlight" else 3))
        poly_item.setBrush(QBrush(Qt.NoBrush))
        poly_item.setVisible(self._markers_visible)
        self._scene.addItem(poly_item)
        self._frame_items.append(poly_item)

        # 标签布局：F1 交互模式永远全长（D39），主预览走省略/降级链（D35/D33）
        rect = poly.boundingRect()
        font = QFont()
        font_px = max(label_font_size(rect.width(), rect.height()),
                      math.ceil(MIN_FONT_PX / self._effective_font_scale()))
        font.setPixelSize(font_px)
        bg_color, text_color, bold = label_style(frame, state)
        font.setBold(bold)
        if self._interactive:
            layout = _full_label_layout(frame, font, img_w, img_h)
        else:
            layout = plan_label(frame, font, img_w, img_h, placed)
        group = QGraphicsItemGroup()
        bg = QGraphicsRectItem(0, 0, layout.w, layout.h, group)
        bg.setPen(QPen(Qt.NoPen))
        bg.setBrush(QBrush(bg_color))
        label = QGraphicsSimpleTextItem(layout.text, group)
        label.setBrush(QBrush(text_color))
        label.setFont(font)
        label.setPos(2, 1)
        group.setPos(layout.x, layout.y)
        if layout.angle:
            group.setRotation(layout.angle)
        group.setVisible(self._markers_visible)
        self._scene.addItem(group)
        self._frame_items.append(group)

    # ---- 视图操作 ----

    def fit(self):
        if self._pix_item is not None:
            self.fitInView(self._pix_item, Qt.KeepAspectRatio)
        elif self._message_item is not None:
            self.fitInView(self._message_item, Qt.KeepAspectRatio)
        self._rebuild()  # 缩放变化后重算降级布局

    def _current_scale(self) -> float:
        return self._effective_font_scale()

    def _apply(self, scale: float):
        self.setTransform(QTransform().rotate(self._rotation).scale(scale, scale))
        self._rebuild()

    def zoom_by(self, factor: float):
        self._apply(self._current_scale() * factor)

    def zoom_100(self):
        self._apply(1.0)

    def rotate_by(self, degrees: float):
        self._rotation += degrees
        self._apply(self._current_scale())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._interactive:
            self.fit()

    def wheelEvent(self, event):
        if self._interactive:
            self.zoom_by(1.25 if event.angleDelta().y() > 0 else 0.8)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        # 点击空白恢复常态（清除高亮）
        if self._highlight_content is not None:
            self.set_highlight(None)
            if callable(self.on_blank_click):
                self.on_blank_click()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if callable(self.on_double_click):
            self.on_double_click()
        super().mouseDoubleClickEvent(event)


class PreviewWindow(QDialog):
    """F1 独立预览窗口（非模态）：PreviewView(interactive=True) + 工具栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预览")
        self.resize(900, 700)

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

        self._view = PreviewView(self, interactive=True)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self._view, stretch=1)

    # ---- 数据（转发到 PreviewView）----

    @property
    def _frames(self) -> list[Frame]:
        return self._view._frames

    @property
    def _frame_items(self) -> list:
        return self._view._frame_items

    @property
    def _scene(self) -> QGraphicsScene:
        return self._view._scene

    @property
    def _highlight_content(self) -> str | None:
        return self._view._highlight_content

    def set_image(self, title: str, pixmap: QPixmap, frames: list[Frame],
                  highlight_content: str | None = None):
        """设置图片与标记帧（列表切换时跟随调用）。换图重置高亮态。"""
        self.setWindowTitle(f"预览 - {title}")
        self._view.set_image(pixmap, frames)
        self._view.set_highlight(highlight_content)

    def set_highlight(self, content: str | None):
        self._view.set_highlight(content)

    # ---- 视图操作 ----

    def fit(self):
        self._view.fit()

    def zoom_100(self):
        self._view.zoom_100()

    def zoom_by(self, factor: float):
        self._view.zoom_by(factor)

    def zoom_in(self):
        self.zoom_by(1.25)

    def zoom_out(self):
        self.zoom_by(0.8)

    def rotate_left(self):
        self._view.rotate_by(-90)

    def rotate_right(self):
        self._view.rotate_by(90)

    def _on_markers_toggled(self, checked: bool):
        self._view.set_markers_visible(checked)
