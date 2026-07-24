"""主窗口：文件列表 / 预览高亮 / 结果表格 / 模板导出 / 状态持久化。"""
from __future__ import annotations

import atexit
import hashlib
import logging
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths as app_paths  # noqa: E402
from decoder import (FORMAT_WHITELIST, DecodeResult, attempts_to_dicts,  # noqa: E402
                     decode_image_detailed, extract_features_from_path,
                     formats_flag)
from exporter import (DEFAULT_TEMPLATE, ExportFilter, ExportRecord, apply_filter,  # noqa: E402
                      export, render_template, render_two_stage,
                      warn_unknown_placeholders)
from history import History, HistoryRecord  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from renamer import execute_rename  # noqa: E402
from templates import TemplateStore, filter_from_dict, filter_to_dict  # noqa: E402
from ui.export_settings_dialog import ExportSettingsDialog  # noqa: E402
from ui.formats_dialog import FormatsDialog  # noqa: E402
from ui.preview_window import (Frame, PreviewView, PreviewWindow, build_frames,  # noqa: E402
                               frame_angle, frame_color, frame_label,
                               frame_state, label_font_size, label_placement,
                               label_style, rotated_label_anchor,
                               LABEL_ANGLE_THRESHOLD)
from ui.history_dialog import HistoryDialog  # noqa: E402
from ui.rename_dialog import RenameDialog  # noqa: E402

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}

PLACEHOLDERS = ["{index}", "{filename}", "{type}", "{content}", "{count}", "{date}", "{time}"]

# QSettings 键
K_GEOMETRY = "ui/geometry"
K_TEMPLATE = "export/template"
K_FORMAT = "export/format"
K_DELIMITER = "export/delimiter"
K_LAST_DIR = "export/last_dir"
K_RECENT_IMAGES = "session/recent_images"
K_TIER = "decode/tier"
K_FORMATS = "decode/formats"
K_SUSPECT = "decode/suspect"
K_JOINER = "export/joiner"
K_OUTER = "export/outer"
K_GROUP_BY = "export/group_by"
K_FILTER_TYPES = "export/filter_types"
K_FILTER_MIN = "export/filter_min"
K_FILTER_MAX = "export/filter_max"
K_FILTER_PREFIX = "export/filter_prefix"
K_FILTER_REGEX = "export/filter_regex"
K_PROFILE = "decode/profile"
K_TEMPLATE_NAME = "export/template_name"


def collect_image_paths(paths: list[str]) -> list[str]:
    """展开文件夹，过滤出图片路径。"""
    out = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for full in sorted(path.rglob("*")):
                if full.is_file() and full.suffix.lower() in IMAGE_EXTS:
                    out.append(str(full))
        elif path.suffix.lower() in IMAGE_EXTS:
            out.append(str(path))
    return out


class _WorkerSignals(QObject):
    finished = Signal(str, list, str, dict)  # path, results, error, meta(attempts/sha256/features)


# 进程级 worker 注册表：worker 生命周期与窗口解耦（D37 竞态修复）。
# 窗口 close+GC 后 self._workers 集合被销毁会导致 worker 的 signals 被删、
# emit 抛 RuntimeError；改由模块级注册表持有 worker 至 run() 结束。
_ACTIVE_WORKERS: set = set()


def _wait_workers_at_exit():
    """解释器退出前的兜底等待（D41）：atexit 先于模块全局回收执行，
    给后台 worker 收尾窗口，避免关闭期间 emit 撞到被回收的 signals。"""
    QThreadPool.globalInstance().waitForDone(5000)


atexit.register(_wait_workers_at_exit)


class _DecodeWorker(QRunnable):
    def __init__(self, path: str, tier: str = "balanced",
                 format_names: list[str] | None = None,
                 include_suspect: bool = True, profile=None):
        super().__init__()
        self.path = path
        self.tier = tier
        self.format_names = format_names
        self.include_suspect = include_suspect
        self.profile = profile
        self.signals = _WorkerSignals()

    def run(self):
        _ACTIVE_WORKERS.add(self)
        try:
            self._run()
        finally:
            _ACTIVE_WORKERS.discard(self)

    def _run(self):
        start = time.perf_counter()
        error = ""
        try:
            results, attempts = decode_image_detailed(
                self.path, tier=self.tier,
                formats=formats_flag(self.format_names),
                include_suspect=self.include_suspect,
                profile=self.profile)
        except Exception as exc:  # noqa: BLE001
            logger.exception("解码失败: %s", self.path)
            results, attempts, error = [], [], str(exc)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("解码 %s: %d 个码, %.0f ms", self.path, len(results), elapsed_ms)
        meta = {"attempts": attempts_to_dicts(attempts)}
        try:
            meta["sha256"] = hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
            meta["features"] = extract_features_from_path(self.path)
        except Exception:  # noqa: BLE001 - 元数据失败不影响解码结果
            logger.exception("图像特征/哈希提取失败: %s", self.path)
        self.signals.finished.emit(self.path, results, error, meta)


class PreviewArea(PreviewView):
    """主预览区：PreviewView 嵌入模式（统一渲染，D32）+ 按路径加载图片。"""

    def __init__(self):
        super().__init__(None, interactive=False)
        self.setMinimumSize(320, 240)

    def show_image(self, path: str, frames: list[Frame]):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            # 加载失败必须清空旧内容并明示，否则预览区残留上一张图（看似"失效/串图"）
            logger.warning("预览加载失败: %s", path)
            self.set_message(f"无法加载图片:\n{path}")
            return
        # 换图恢复常态（清除点击高亮，F3）
        self._highlight_content = None
        self.set_image(pixmap, frames)


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None,
                 history_db: str | Path | None = None,
                 profile_store: ProfileStore | None = None,
                 template_store: TemplateStore | None = None):
        super().__init__()
        self.setWindowTitle("批量条码/二维码识别导出工具")
        self.resize(1100, 700)
        self.setAcceptDrops(True)

        self._settings = settings or QSettings(app_paths.ORG_NAME, app_paths.APP_NAME)
        self._profiles = profile_store or ProfileStore()
        self._templates = template_store or TemplateStore()
        self._preview_window: PreviewWindow | None = None  # F1 独立预览窗口（懒创建）
        # 历史库初始化失败不阻塞主流程
        try:
            db_path = Path(history_db) if history_db else app_paths.data_dir() / "history.db"
            self._history: History | None = History(db_path)
        except Exception:  # noqa: BLE001
            logger.exception("历史库初始化失败")
            self._history = None
        self.results: dict[str, list[DecodeResult]] = {}  # path -> results
        self.errors: dict[str, str] = {}
        self._pending = 0
        self._pool = QThreadPool.globalInstance()
        # 粘贴的剪贴板图片落盘到会话临时目录，退出时清理；不写入会话持久化列表
        self._clipboard_dir = Path(tempfile.mkdtemp(prefix="barcode-reader-clipboard-"))
        self._paste_counter = 0
        atexit.register(self._cleanup_clipboard_dir)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧：文件列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加图片…")
        add_btn.clicked.connect(self.add_files_dialog)
        paste_btn = QPushButton("粘贴图片")
        paste_btn.setToolTip("粘贴剪贴板中的图片或文件路径 (Ctrl/Cmd+V)")
        paste_btn.clicked.connect(self.paste_from_clipboard)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self.clear_all)
        rename_btn = QPushButton("按码重命名…")
        rename_btn.clicked.connect(self.rename_by_code)
        history_btn = QPushButton("历史…")
        history_btn.clicked.connect(self.open_history)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(paste_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(rename_btn)
        btn_row.addWidget(history_btn)
        btn_row.addStretch(1)
        log_btn = QPushButton("打开日志目录")
        log_btn.clicked.connect(self.open_log_dir)
        btn_row.addWidget(log_btn)
        left_layout.addLayout(btn_row)
        # Ctrl/Cmd+V 快捷键（QKeySequence.Paste 按平台映射）
        QShortcut(QKeySequence.Paste, self, activated=self.paste_from_clipboard)
        self.file_list = QListWidget()
        # 拖放统一由 MainWindow 处理：子控件（含 viewport）必须关闭 acceptDrops，
        # 否则 QListWidget/QTableWidget 默认拦截 drop 事件，主窗口收不到
        self.file_list.setAcceptDrops(False)
        self.file_list.viewport().setAcceptDrops(False)
        self.file_list.setIconSize(self.file_list.iconSize())
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._file_context_menu)
        self.file_list.currentRowChanged.connect(self._on_file_selected)
        # 点击已选中项（currentRow 不变不发信号）也强制刷新预览，
        # 兜底任何预览与选择状态脱节的情形
        self.file_list.itemClicked.connect(lambda _item: self._refresh_current_preview())
        # 双击列表项打开 F1 独立预览窗口
        self.file_list.itemDoubleClicked.connect(lambda _item: self.open_preview_window())
        left_layout.addWidget(self.file_list)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        left_layout.addWidget(self.progress)
        splitter.addWidget(left)

        # 右侧：预览 + 结果表格
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.preview = PreviewArea()
        self.preview.on_double_click = self.open_preview_window
        right_layout.addWidget(self.preview, stretch=3)
        self.table = QTableWidget(0, 4)
        self.table.setAcceptDrops(False)
        self.table.viewport().setAcceptDrops(False)
        self.table.setHorizontalHeaderLabels(["序号", "文件名", "码制", "内容"])
        # 隐藏 QTableWidget 默认行号表头（与自有「序号」列重复）
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.cellClicked.connect(self._on_table_clicked)
        right_layout.addWidget(self.table, stretch=2)
        copy_row = QHBoxLayout()
        self.dedup_check = QCheckBox("去重视图")
        self.dedup_check.setToolTip("按码内容去重，每个唯一码一行，显示出现次数与来源文件")
        self.dedup_check.toggled.connect(self._on_dedup_toggled)
        copy_row.addWidget(self.dedup_check)
        copy_one_btn = QPushButton("复制选中内容")
        copy_one_btn.clicked.connect(self.copy_selected)
        copy_all_btn = QPushButton("复制全部内容")
        copy_all_btn.clicked.connect(self.copy_all)
        copy_row.addWidget(copy_one_btn)
        copy_row.addWidget(copy_all_btn)
        copy_row.addStretch(1)
        right_layout.addLayout(copy_row)
        splitter.addWidget(right)
        splitter.setSizes([350, 750])

        # 底部：模板 + 导出
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(QLabel("模板:"))
        self.tpl_pool_combo = QComboBox()
        self.tpl_pool_combo.addItem("（当前编辑）")
        self.tpl_pool_combo.addItems(self._templates.names())
        self.tpl_pool_combo.setCurrentIndex(0)
        self.tpl_pool_combo.currentTextChanged.connect(self._on_tpl_pool_changed)
        tpl_row.addWidget(self.tpl_pool_combo)
        tpl_save_btn = QPushButton("存为模板")
        tpl_save_btn.setToolTip("把当前导出配置（模板/连接符/外模板/分组/格式/分隔符/过滤）存入模板池")
        tpl_save_btn.clicked.connect(self.save_template_as)
        tpl_row.addWidget(tpl_save_btn)
        self.tpl_del_btn = QPushButton("删除")
        self.tpl_del_btn.clicked.connect(self.delete_template)
        tpl_row.addWidget(self.tpl_del_btn)
        self.template_edit = QLineEdit(DEFAULT_TEMPLATE)
        self.template_edit.textChanged.connect(self._refresh_template_preview)
        tpl_row.addWidget(self.template_edit, stretch=1)
        for ph in PLACEHOLDERS:
            b = QToolButton()
            b.setText(ph)
            b.clicked.connect(lambda _checked=False, p=ph: self.template_edit.insert(p))
            tpl_row.addWidget(b)
        bottom_layout.addLayout(tpl_row)
        self.tpl_preview = QLabel("")
        self.tpl_preview.setStyleSheet("color: gray;")
        self.tpl_preview.setWordWrap(True)
        bottom_layout.addWidget(self.tpl_preview)
        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("格式:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["TXT", "CSV", "XLSX", "JSON"])
        export_row.addWidget(self.format_combo)
        export_row.addWidget(QLabel("分隔符:"))
        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItem("逗号 (,)", ",")
        self.delimiter_combo.addItem("Tab", "\t")
        export_row.addWidget(self.delimiter_combo)
        settings_btn = QPushButton("导出设置…")
        settings_btn.setToolTip("两段式（连接符/外模板/分组）与导出过滤")
        settings_btn.clicked.connect(self.open_export_settings)
        export_row.addWidget(settings_btn)
        clip_btn = QPushButton("复制到剪贴板")
        clip_btn.setToolTip("按当前模板+过滤渲染后进系统剪贴板，不落盘")
        clip_btn.clicked.connect(self.copy_rendered_to_clipboard)
        export_row.addWidget(clip_btn)
        export_btn = QPushButton("导出…")
        export_btn.clicked.connect(self.export_results)
        export_row.addWidget(export_btn)
        export_row.addStretch(1)
        bottom_layout.addLayout(export_row)
        # 识别设置行：profile / 档位 / 码制白名单 / 疑似码开关
        decode_row = QHBoxLayout()
        decode_row.addWidget(QLabel("档案:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(self._profiles.names())
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        decode_row.addWidget(self.profile_combo)
        profile_btn = QPushButton("参数…")
        profile_btn.setToolTip("查看/编辑当前档案的全部识别参数（含恢复默认）")
        profile_btn.clicked.connect(self.edit_profile)
        decode_row.addWidget(profile_btn)
        self.profile_del_btn = QPushButton("删除")
        self.profile_del_btn.clicked.connect(self.delete_profile)
        decode_row.addWidget(self.profile_del_btn)
        decode_row.addWidget(QLabel("档位:"))
        self.tier_combo = QComboBox()
        self.tier_combo.addItem("快速（仅直读）", "fast")
        self.tier_combo.addItem("均衡（默认）", "balanced")
        self.tier_combo.addItem("极限（全层组合）", "max")
        self.tier_combo.setCurrentIndex(1)
        decode_row.addWidget(self.tier_combo)
        self.formats_btn = QPushButton("码制…")
        self.formats_btn.setToolTip("码制白名单（默认全选）")
        self.formats_btn.clicked.connect(self.choose_formats)
        decode_row.addWidget(self.formats_btn)
        self.suspect_check = QCheckBox("含疑似码")
        self.suspect_check.setToolTip("把校验失败的码标为疑似结果（码制列带 ?，浅黄底）")
        self.suspect_check.setChecked(True)
        decode_row.addWidget(self.suspect_check)
        decode_row.addStretch(1)
        bottom_layout.addLayout(decode_row)
        self._format_names: list[str] = list(FORMAT_WHITELIST)
        # 两段式与过滤的当前配置（持久化到 export/ 组）
        self._joiner = "\n"
        self._outer = "{items}"
        self._group_by = "none"
        self._filter = ExportFilter()

        container = QWidget()
        v = QVBoxLayout(container)
        v.addWidget(splitter, stretch=1)
        v.addWidget(bottom)
        self.setCentralWidget(container)

        self.statusBar().showMessage("拖入图片或点击“添加图片”开始")

        self._restore_settings()
        self._notify_corrupt_stores()

    def _notify_corrupt_stores(self):
        """配置文件损坏提示（一次性弹窗 + 状态栏 + 日志，D25）：
        用户自定义内容已回落默认，必须让用户知晓并去 .bak 抢救。"""
        reports = []
        for label, store in (("识别档案池 profiles.json", self._profiles),
                             ("导出模板池 templates.json", self._templates)):
            backup = getattr(store, "corrupt_backup", None)
            if backup:
                reports.append(f"{label} → 已备份到 {backup}")
        if not reports:
            return
        detail = "\n".join(reports)
        logger.warning("配置文件损坏，已备份并回落默认:\n%s", detail)
        self.statusBar().showMessage("配置文件损坏：已备份原文件并回落默认", 8000)
        QMessageBox.warning(
            self, "配置文件损坏",
            "检测到配置文件损坏，自定义内容已回落默认（程序可正常使用）。\n"
            "原文件已备份，可手动抢救：\n" + detail)

    # ---------- 状态持久化 ----------

    def _restore_settings(self):
        s = self._settings
        geometry = s.value(K_GEOMETRY)
        if geometry:
            self.restoreGeometry(geometry)
        template = s.value(K_TEMPLATE, "")
        if template:
            self.template_edit.setText(template)
        fmt = s.value(K_FORMAT, "")
        if fmt in ("TXT", "CSV"):
            self.format_combo.setCurrentText(fmt)
        delim = s.value(K_DELIMITER, "")
        idx = self.delimiter_combo.findData(delim)
        if idx >= 0:
            self.delimiter_combo.setCurrentIndex(idx)
        tier = s.value(K_TIER, "")
        idx = self.tier_combo.findData(tier)
        if idx >= 0:
            self.tier_combo.setCurrentIndex(idx)
        fmts = s.value(K_FORMATS)
        if isinstance(fmts, str):
            fmts = [fmts]
        if fmts:
            self._format_names = [f for f in fmts if f in FORMAT_WHITELIST] or \
                list(FORMAT_WHITELIST)
            self.formats_btn.setText(
                "码制…" if len(self._format_names) == len(FORMAT_WHITELIST)
                else f"码制({len(self._format_names)})…")
        suspect = s.value(K_SUSPECT)
        if suspect is not None:
            self.suspect_check.setChecked(suspect not in (False, "false", "0", 0))
        profile_name = s.value(K_PROFILE)
        if profile_name and profile_name in self._profiles.names():
            self.profile_combo.setCurrentText(profile_name)
        self._on_profile_changed(self.profile_combo.currentText())
        tpl_name = s.value(K_TEMPLATE_NAME)
        if tpl_name and self._templates.get(tpl_name):
            self.tpl_pool_combo.setCurrentText(tpl_name)
            self._apply_export_config(self._templates.get(tpl_name))
        joiner = s.value(K_JOINER)
        if joiner is not None:
            self._joiner = joiner
        outer = s.value(K_OUTER)
        if outer:
            self._outer = outer
        group_by = s.value(K_GROUP_BY)
        if group_by in ("none", "image", "global"):
            self._group_by = group_by
        ftypes = s.value(K_FILTER_TYPES)
        if isinstance(ftypes, str):
            ftypes = [ftypes]
        self._filter = ExportFilter(
            types=[t for t in (ftypes or []) if t in FORMAT_WHITELIST.values()] or None,
            min_len=self._int_setting(s.value(K_FILTER_MIN)),
            max_len=self._int_setting(s.value(K_FILTER_MAX)),
            prefix=s.value(K_FILTER_PREFIX, "") or "",
            regex=s.value(K_FILTER_REGEX, "") or "",
        )
        recent = s.value(K_RECENT_IMAGES, [])
        if isinstance(recent, str):
            recent = [recent]
        recent = [p for p in (recent or []) if Path(p).is_file()]
        if recent:
            logger.info("恢复上次会话的 %d 张图片", len(recent))
            self.add_paths(recent)

    def choose_formats(self):
        dialog = FormatsDialog(self._format_names, self)
        if dialog.exec():
            self._format_names = dialog.selected()
            self.formats_btn.setText(
                "码制…" if len(self._format_names) == len(FORMAT_WHITELIST)
                else f"码制({len(self._format_names)})…")

    def _decode_options(self) -> dict:
        return {"tier": self.tier_combo.currentData(),
                "format_names": self._format_names,
                "include_suspect": self.suspect_check.isChecked(),
                "profile": self._profiles.get(self.profile_combo.currentText())}

    # ---------- 识别参数档案池 ----------

    def _on_profile_changed(self, name: str):
        self.profile_del_btn.setEnabled(not self._profiles.is_builtin(name))

    def edit_profile(self):
        from ui.profile_dialog import ProfileDialog
        name = self.profile_combo.currentText()
        dialog = ProfileDialog(name, self._profiles.get(name), self)
        if not dialog.exec():
            return
        new_name, profile = dialog.profile_name, dialog.profile
        try:
            if self._profiles.is_builtin(name) and new_name == name:
                QMessageBox.information(self, "参数档案",
                                        "内置「默认」档案不可修改，请改用新名称另存")
                return
            if new_name != name and new_name in self._profiles.names():
                self._profiles.save(new_name, profile)  # 覆盖已有
            elif new_name != name and not self._profiles.is_builtin(name):
                self._profiles.save(new_name, profile)
                self._profiles.delete(name)  # 重命名
            else:
                self._profiles.save(new_name, profile)
        except ValueError as exc:
            QMessageBox.warning(self, "参数档案", str(exc))
            return
        self._reload_profile_combo(new_name)
        self.statusBar().showMessage(f"档案已保存: {new_name}", 5000)

    def delete_profile(self):
        name = self.profile_combo.currentText()
        try:
            self._profiles.delete(name)
        except ValueError as exc:
            QMessageBox.warning(self, "参数档案", str(exc))
            return
        self._reload_profile_combo(self._profiles.names()[0])
        self.statusBar().showMessage(f"档案已删除: {name}", 5000)

    def _reload_profile_combo(self, select: str):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(self._profiles.names())
        self.profile_combo.setCurrentText(select)
        self.profile_combo.blockSignals(False)
        self._on_profile_changed(select)

    # ---------- 导出模板池 ----------

    def _current_export_config(self) -> dict:
        return {"template": self.template_edit.text() or DEFAULT_TEMPLATE,
                "joiner": self._joiner, "outer": self._outer,
                "group_by": self._group_by,
                "format": self.format_combo.currentText(),
                "delimiter": self.delimiter_combo.currentData(),
                "filter": filter_to_dict(self._filter)}

    def _apply_export_config(self, config: dict):
        self.template_edit.setText(config.get("template", DEFAULT_TEMPLATE))
        self._joiner = config.get("joiner", "\n")
        self._outer = config.get("outer", "{items}")
        self._group_by = config.get("group_by", "none")
        fmt = config.get("format", "TXT")
        if fmt in ("TXT", "CSV", "XLSX", "JSON"):
            self.format_combo.setCurrentText(fmt)
        idx = self.delimiter_combo.findData(config.get("delimiter", ","))
        if idx >= 0:
            self.delimiter_combo.setCurrentIndex(idx)
        self._filter = filter_from_dict(config.get("filter"))
        self._refresh_template_preview()

    def _on_tpl_pool_changed(self, name: str):
        if name == "（当前编辑）":
            return
        config = self._templates.get(name)
        if config:
            self._apply_export_config(config)

    def save_template_as(self):
        from PySide6.QtWidgets import QInputDialog
        current = self.tpl_pool_combo.currentText()
        default = "" if current == "（当前编辑）" else current
        name, ok = QInputDialog.getText(self, "存为模板", "模板名称:", text=default)
        name = name.strip()
        if not ok or not name:
            return
        try:
            self._templates.save(name, self._current_export_config())
        except ValueError as exc:
            QMessageBox.warning(self, "模板池", str(exc))
            return
        self._reload_tpl_pool_combo(name)
        self.statusBar().showMessage(f"模板已保存: {name}", 5000)

    def delete_template(self):
        name = self.tpl_pool_combo.currentText()
        if name == "（当前编辑）":
            return
        self._templates.delete(name)
        self._reload_tpl_pool_combo("（当前编辑）")
        self.statusBar().showMessage(f"模板已删除: {name}", 5000)

    def _reload_tpl_pool_combo(self, select: str):
        self.tpl_pool_combo.blockSignals(True)
        self.tpl_pool_combo.clear()
        self.tpl_pool_combo.addItem("（当前编辑）")
        self.tpl_pool_combo.addItems(self._templates.names())
        self.tpl_pool_combo.setCurrentText(select)
        self.tpl_pool_combo.blockSignals(False)

    @staticmethod
    def _int_setting(value) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def open_export_settings(self):
        dialog = ExportSettingsDialog(self._joiner, self._outer, self._group_by,
                                      self._filter, self)
        if dialog.exec():
            self._joiner = dialog.joiner
            self._outer = dialog.outer
            self._group_by = dialog.group_by
            self._filter = dialog.export_filter()
            self._refresh_template_preview()

    def _save_settings(self):
        s = self._settings
        s.setValue(K_GEOMETRY, self.saveGeometry())
        s.setValue(K_TEMPLATE, self.template_edit.text())
        s.setValue(K_FORMAT, self.format_combo.currentText())
        s.setValue(K_DELIMITER, self.delimiter_combo.currentData())
        s.setValue(K_TIER, self.tier_combo.currentData())
        s.setValue(K_FORMATS, self._format_names)
        s.setValue(K_SUSPECT, self.suspect_check.isChecked())
        s.setValue(K_JOINER, self._joiner)
        s.setValue(K_OUTER, self._outer)
        s.setValue(K_GROUP_BY, self._group_by)
        s.setValue(K_FILTER_TYPES, self._filter.types or [])
        s.setValue(K_FILTER_MIN, "" if self._filter.min_len is None else self._filter.min_len)
        s.setValue(K_FILTER_MAX, "" if self._filter.max_len is None else self._filter.max_len)
        s.setValue(K_FILTER_PREFIX, self._filter.prefix)
        s.setValue(K_FILTER_REGEX, self._filter.regex)
        s.setValue(K_PROFILE, self.profile_combo.currentText())
        s.setValue(K_TEMPLATE_NAME, self.tpl_pool_combo.currentText())
        # 粘贴的临时图是会话级产物，不写入持久化的最近会话列表
        images = [self.file_list.item(i).data(Qt.UserRole)
                  for i in range(self.file_list.count())
                  if not Path(self.file_list.item(i).data(Qt.UserRole)).is_relative_to(self._clipboard_dir)]
        s.setValue(K_RECENT_IMAGES, images)
        s.sync()

    def closeEvent(self, event):
        self._save_settings()
        self._cleanup_clipboard_dir()
        logger.info("主窗口关闭，状态已保存")
        super().closeEvent(event)

    # ---------- 剪贴板粘贴 ----------

    def _cleanup_clipboard_dir(self):
        shutil.rmtree(self._clipboard_dir, ignore_errors=True)

    def paste_from_clipboard(self):
        """粘贴剪贴板内容：图片数据 → 落盘临时 PNG 后走 add_paths 解码流程；
        文件 URL / 路径文本 → 解析后走 add_paths。无可用内容时状态栏提示。

        跨平台说明：Windows 截图在剪贴板中多为 DIB 格式，Qt 的
        QClipboard.image() 已归一化为 QImage（本机 macOS 验证，Windows
        行为依 Qt 文档，未实机验证）。
        """
        mime = QApplication.clipboard().mimeData()
        if mime is not None and mime.hasImage():
            image = QApplication.clipboard().image()
            if not image.isNull():
                self._paste_counter += 1
                png = self._clipboard_dir / f"clipboard_{self._paste_counter:03d}.png"
                if image.save(str(png), "PNG"):
                    logger.info("粘贴剪贴板图片 -> %s", png)
                    self.add_paths([str(png)])
                    return
                logger.error("剪贴板图片保存失败: %s", png)
        if mime is not None and mime.hasUrls():
            paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if paths:
                logger.info("粘贴 %d 个文件 URL", len(paths))
                self.add_paths(paths)
                return
        if mime is not None and mime.hasText():
            paths = [line.strip() for line in mime.text().splitlines() if line.strip()]
            paths = [p for p in paths if Path(p).exists()]
            if paths:
                logger.info("粘贴 %d 个路径文本", len(paths))
                self.add_paths(paths)
                return
        self.statusBar().showMessage("剪贴板中没有可识别的图片或文件路径", 5000)
        logger.info("粘贴：剪贴板无可识别内容")

    # ---------- 日志 ----------

    def open_log_dir(self):
        directory = app_paths.log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            logger.warning("打开日志目录失败: %s", directory)
            self.statusBar().showMessage(f"无法打开日志目录: {directory}", 8000)

    # ---------- 拖入（MainWindow 级别统一处理，子控件已关闭 acceptDrops） ----------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self.add_paths(paths)

    # ---------- 文件管理 ----------

    def add_files_dialog(self):
        # DontUseNativeDialog + qtbase_zh_CN 翻译，保证三平台对话框均为中文
        #（原生对话框跟随系统语言，系统为英文时无法保证中文）
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)",
            options=QFileDialog.DontUseNativeDialog)
        self.add_paths(paths)

    def add_paths(self, paths: list[str]):
        images = []
        for p in collect_image_paths(paths):
            if p not in self.results and p not in images:
                images.append(p)
        if not images:
            return
        logger.info("添加 %d 张图片", len(images))
        for p in images:
            self.results[p] = []
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            thumb = QPixmap(p).scaledToHeight(48, Qt.SmoothTransformation)
            if not thumb.isNull():
                from PySide6.QtGui import QIcon
                item.setIcon(QIcon(thumb))
            item.setText(f"{Path(p).name}  [识别中…]")
            self.file_list.addItem(item)
        self._pending = len(images)
        self.progress.setVisible(True)
        self.progress.setRange(0, self._pending)
        self.progress.setValue(0)
        opts = self._decode_options()
        for p in images:
            worker = _DecodeWorker(p, **opts)
            worker.signals.finished.connect(
                lambda path, results, error, meta, w=worker:
                self._on_decoded(w, path, results, error, meta))
            self._pool.start(worker)

    def _on_decoded(self, worker: "_DecodeWorker", path: str, results: list,
                    error: str, meta: dict | None = None):
        meta = meta or {}
        self.results[path] = results
        if error:
            self.errors[path] = error
        else:
            self._write_strategy_log(path, results, meta)
            if results:
                self._write_history(path, results)
        self._pending -= 1
        self.progress.setValue(self.progress.maximum() - self._pending)
        # 更新列表项状态
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) == path:
                if error:
                    item.setText(f"{Path(path).name}  [读取失败]")
                elif results:
                    item.setText(f"{Path(path).name}  [{len(results)} 个码]")
                else:
                    item.setText(f"{Path(path).name}  [未识别到码]")
                break
        if self._pending <= 0:
            self.progress.setVisible(False)
            failed = sorted(self.errors)
            if failed:
                # 批量失败汇总（D25 三档：状态栏 8s + 日志含失败清单，不弹窗骚扰）
                success = len(self.results) - len(failed)
                self.statusBar().showMessage(
                    f"批量完成：成功 {success} 张，失败 {len(failed)} 张", 8000)
                logger.warning("批量解码完成：成功 %d 张，失败 %d 张: %s",
                               success, len(failed),
                               "; ".join(Path(p).name for p in failed))
            else:
                total = sum(len(v) for v in self.results.values())
                self.statusBar().showMessage(
                    f"共 {len(self.results)} 张图，识别到 {total} 个码")
        self._rebuild_table()
        self._refresh_template_preview()
        current = self.file_list.currentItem()
        if current and current.data(Qt.UserRole) == path:
            self.preview.set_frames(self._frames_for(path))
            self._sync_preview_window()

    def clear_all(self):
        self.results.clear()
        self.errors.clear()
        self.file_list.clear()
        self.table.setRowCount(0)
        self.preview.clear_image()
        self._sync_preview_window()
        self.statusBar().showMessage("已清空")

    def _file_context_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        rescan = QAction("增强重扫（极限档）", self)
        rescan.triggered.connect(lambda: self.rescan_item(item))
        menu.addAction(rescan)
        remove = QAction("移除", self)
        remove.triggered.connect(lambda: self._remove_item(item))
        menu.addAction(remove)
        menu.exec(self.file_list.viewport().mapToGlobal(pos))

    def rescan_item(self, item):
        """单图增强重扫：强制极限档重新识别，只影响该图。"""
        path = item.data(Qt.UserRole)
        logger.info("增强重扫: %s", path)
        item.setText(f"{Path(path).name}  [重扫中…]")
        opts = self._decode_options()
        opts["tier"] = "max"
        worker = _DecodeWorker(path, **opts)
        self._pending += 1
        self.progress.setVisible(True)
        self.progress.setRange(0, max(self.progress.maximum(), self._pending))
        worker.signals.finished.connect(
            lambda p, results, error, meta, w=worker: self._on_decoded(w, p, results, error, meta))
        self._pool.start(worker)

    def _remove_item(self, item):
        path = item.data(Qt.UserRole)
        self.results.pop(path, None)
        self.errors.pop(path, None)
        self.file_list.takeItem(self.file_list.row(item))
        self._rebuild_table()
        # 不能盲目 clear_image：移除未选中项时会误清预览；且剩余单图
        # currentRow 不变、currentRowChanged 不再触发，预览会永远停在清空态。
        # 统一刷新当前选中项的预览（无选中则清空）
        self._refresh_current_preview()

    def _refresh_current_preview(self):
        """按当前选中项刷新预览；无选中项时清空。F1 窗口同步跟随。"""
        current = self.file_list.currentItem()
        if current is None:
            self.preview.clear_image()
            self._sync_preview_window()
            return
        path = current.data(Qt.UserRole)
        self.preview.show_image(path, self._frames_for(path))
        self._sync_preview_window()

    # ---------- 标记帧 / 高亮 / F1 独立预览 ----------

    def _frames_for(self, path: str) -> list[Frame]:
        """构建某图的标记帧，序号与结果表格「序号」列一致（跨图累加，F2）。"""
        seq = 1
        for p, r in self._all_records():
            if p == path:
                break
            seq += 1
        return build_frames(self.results.get(path, []), seq)

    def _current_preview_path(self) -> str | None:
        current = self.file_list.currentItem()
        return current.data(Qt.UserRole) if current else None

    def open_preview_window(self):
        """打开/复用 F1 独立预览窗口（非模态），内容跟随当前选中图。"""
        if self._preview_window is None:
            self._preview_window = PreviewWindow(self)
        self._preview_window.show()
        self._preview_window.raise_()
        self._sync_preview_window()

    def _sync_preview_window(self):
        if self._preview_window is None or not self._preview_window.isVisible():
            return
        path = self._current_preview_path()
        if path is None:
            self._preview_window.set_image("（无选择）", QPixmap(), [])
            return
        self._preview_window.set_image(
            Path(path).name, QPixmap(path), self._frames_for(path),
            self.preview._highlight_content)

    # ---------- 结果展示 ----------

    def _write_strategy_log(self, path: str, results: list, meta: dict):
        """识别管线策略日志写入历史库；失败只记日志，不影响主流程。
        final_hit_count 只计有效码（不含疑似码）。"""
        if self._history is None or not meta:
            return
        try:
            valid = [r for r in results if not r.suspect]
            self._history.add_strategy_log(
                image_sha256=meta.get("sha256", ""),
                features=meta.get("features", {}),
                attempts=meta.get("attempts", []),
                final_strategy=valid[0].strategy if valid else "",
                final_hit_count=len(valid),
            )
        except Exception:  # noqa: BLE001
            logger.exception("策略日志写入失败: %s", path)

    def _write_history(self, path: str, results: list):
        """解码结果写入历史库；失败只记日志，不影响主流程。
        疑似码不写入正式记录（strategy_log 中仍有过程数据）。"""
        if self._history is None:
            return
        try:
            now = datetime.now()
            self._history.add_batch([
                HistoryRecord(ts=now.isoformat(timespec="seconds"),
                              filename=Path(path).name, type=r.format,
                              content=r.content, source_path=path)
                for r in results if not r.suspect
            ])
        except Exception:  # noqa: BLE001
            logger.exception("历史记录写入失败: %s", path)

    def _all_records(self) -> list[tuple[str, DecodeResult]]:
        out = []
        for i in range(self.file_list.count()):
            path = self.file_list.item(i).data(Qt.UserRole)
            for r in self.results.get(path, []):
                out.append((path, r))
        return out

    def _dedup_records(self) -> list[tuple[list[str], DecodeResult]]:
        """按码内容去重（疑似码与有效码分开成组）：返回 [(来源路径列表, 首个 DecodeResult)]。"""
        groups: dict[tuple[str, bool], tuple[list[str], DecodeResult]] = {}
        for path, r in self._all_records():
            key = (r.content, r.suspect)
            if key in groups:
                groups[key][0].append(path)
            else:
                groups[key] = ([path], r)
        return list(groups.values())

    def _on_dedup_toggled(self, _checked: bool):
        self._rebuild_table()
        self._refresh_template_preview()

    def _rebuild_table(self):
        if self.dedup_check.isChecked():
            self._rebuild_table_dedup()
            return
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["序号", "文件名", "码制", "内容"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        records = self._all_records()
        self.table.setRowCount(len(records))
        for row, (path, r) in enumerate(records):
            self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(Path(path).name))
            self.table.setItem(row, 2, QTableWidgetItem(r.format + ("?" if r.suspect else "")))
            item = QTableWidgetItem(r.content)
            item.setData(Qt.UserRole, path)
            self.table.setItem(row, 3, item)
            if r.suspect:
                self._mark_suspect_row(row, 4)

    def _rebuild_table_dedup(self):
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["序号", "次数", "码制", "内容", "来源文件"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        groups = self._dedup_records()
        self.table.setRowCount(len(groups))
        for row, (sources, r) in enumerate(groups):
            self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(str(len(sources))))
            self.table.setItem(row, 2, QTableWidgetItem(r.format + ("?" if r.suspect else "")))
            self.table.setItem(row, 3, QTableWidgetItem(r.content))
            src = QTableWidgetItem("; ".join(Path(p).name for p in sources))
            src.setToolTip("\n".join(sources))
            src.setData(Qt.UserRole, sources[0])
            self.table.setItem(row, 4, src)
            if r.suspect:
                self._mark_suspect_row(row, 5)

    def _mark_suspect_row(self, row: int, cols: int):
        """疑似码行：浅黄底区分。"""
        from PySide6.QtGui import QColor
        for col in range(cols):
            item = self.table.item(row, col)
            if item:
                item.setBackground(QColor(255, 248, 220))

    def _on_file_selected(self, row: int):
        if row < 0:
            return
        path = self.file_list.item(row).data(Qt.UserRole)
        # 切换图片恢复常态（清除点击高亮，F3）
        self.preview.show_image(path, self._frames_for(path))
        self._sync_preview_window()

    def _on_table_clicked(self, row: int, _col: int):
        # 路径存于行尾单元格的 UserRole（普通视图第 4 列，去重视图第 5 列）
        item = self.table.item(row, self.table.columnCount() - 1)
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        content_item = self.table.item(row, 3)
        content = content_item.text() if content_item else None
        for i in range(self.file_list.count()):
            if self.file_list.item(i).data(Qt.UserRole) == path:
                self.file_list.setCurrentRow(i)
                break
        # F3：被点击码的框加粗变橙、其余变淡（去重视图跳首个来源图并高亮该内容）
        if content:
            self.preview.set_highlight(content)
            if self._preview_window is not None:
                self._preview_window.set_highlight(content)

    def copy_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self.statusBar().showMessage("未选中任何行", 5000)
            return
        text = "\n".join(self.table.item(r, 3).text() for r in rows)
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"已复制 {len(rows)} 条 / {len(text)} 字符", 8000)

    def copy_all(self):
        records = self._filtered_records()
        if not records:
            self.statusBar().showMessage("没有可复制的记录", 5000)
            return
        text = "\n".join(r.content for r in records)
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(
            f"已复制全部 {len(records)} 条 / {len(text)} 字符（含过滤）", 8000)

    # ---------- 模板与导出 ----------

    def _refresh_template_preview(self):
        template = self.template_edit.text()
        records = self._filtered_records()[:3]
        if not records or not template:
            self.tpl_preview.setText("")
            return
        try:
            text = render_two_stage(records, template, self._joiner,
                                    self._outer, self._group_by)
            if len(text) > 200:
                text = text[:200] + "…"
            self.tpl_preview.setText("预览: " + text.replace("\n", "  ⏎  "))
        except Exception as exc:  # noqa: BLE001
            self.tpl_preview.setText(f"模板错误: {exc}")

    def _effective_template(self) -> str:
        """CSV 且分隔符选 Tab 时，把模板中的列分隔逗号换成 Tab。

        占位符名称内部不含逗号，直接替换是安全的。
        """
        template = self.template_edit.text() or DEFAULT_TEMPLATE
        if (self.format_combo.currentText() == "CSV"
                and self.delimiter_combo.currentData() == "\t"
                and "\t" not in template):
            template = template.replace(",", "\t")
        return template

    def _export_records(self) -> list[ExportRecord]:
        """导出用记录：去重模式下每个唯一码一条（含次数与来源列表），否则逐码一条。"""
        if self.dedup_check.isChecked():
            return [ExportRecord(filename="; ".join(Path(p).name for p in sources),
                                 type=r.format, content=r.content,
                                 count=len(sources), suspect=r.suspect)
                    for sources, r in self._dedup_records()]
        return [ExportRecord(Path(p).name, r.format, r.content,
                             suspect=r.suspect)
                for p, r in self._all_records()]

    def _filtered_records(self) -> list[ExportRecord]:
        """导出/复制用记录：应用当前过滤条件。正则非法时按不过滤处理并提示。"""
        records = self._export_records()
        try:
            return apply_filter(records, self._filter)
        except ValueError as exc:
            logger.warning("过滤正则无效，按不过滤处理: %s", exc)
            self.statusBar().showMessage(f"过滤正则无效，已按不过滤处理: {exc}", 8000)
            return records

    def _filter_or_warn(self, records: list[ExportRecord]) -> list[ExportRecord] | None:
        """导出前应用过滤；正则非法弹警告返回 None。"""
        try:
            return apply_filter(records, self._filter)
        except ValueError as exc:
            QMessageBox.warning(self, "导出过滤", f"过滤正则无效: {exc}")
            return None

    def copy_rendered_to_clipboard(self):
        """按当前模板+过滤渲染后进系统剪贴板，不落盘。"""
        records = self._filter_or_warn(self._export_records())
        if records is None:
            return
        if not records:
            QMessageBox.warning(self, "复制到剪贴板", "没有可导出的记录")
            return
        text = render_two_stage(records, self.template_edit.text() or DEFAULT_TEMPLATE,
                                self._joiner, self._outer, self._group_by)
        QApplication.clipboard().setText(text)
        logger.info("按模板复制 %d 条 / %d 字符到剪贴板", len(records), len(text))
        self.statusBar().showMessage(
            f"已按模板复制 {len(records)} 条 / {len(text)} 字符到剪贴板", 8000)

    def export_results(self):
        records = self._filter_or_warn(self._export_records())
        if records is None:
            return
        if not records:
            QMessageBox.information(self, "导出", "没有可导出的识别结果（或全部被过滤）")
            return
        fmt = self.format_combo.currentText().lower()
        last_dir = self._settings.value(K_LAST_DIR, "")
        start = str(Path(last_dir) / f"barcodes.{fmt}") if last_dir else f"barcodes.{fmt}"
        filters = {"txt": "TXT (*.txt)", "csv": "CSV (*.csv)",
                   "xlsx": "Excel (*.xlsx)", "json": "JSON (*.json)"}
        path, _ = QFileDialog.getSaveFileName(
            self, "导出结果", start, filters[fmt],
            options=QFileDialog.DontUseNativeDialog)
        if not path:
            return
        template = self._effective_template()
        unknown = warn_unknown_placeholders(template)
        try:
            export(records, path, fmt, template,
                   header="序号,文件名,码制,内容" if fmt in ("csv", "xlsx") else None,
                   joiner=self._joiner, outer=self._outer, group_by=self._group_by)
        except Exception as exc:  # noqa: BLE001
            logger.exception("导出失败: %s", path)
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        logger.info("导出 %d 条到 %s (格式 %s)", len(records), path, fmt)
        self._settings.setValue(K_LAST_DIR, str(Path(path).parent)
                                )
        self._save_settings()
        msg = f"已导出 {len(records)} 条到 {path}"
        if unknown:
            msg += "\n未知占位符已原样保留: " + ", ".join("{%s}" % u for u in unknown)
        QMessageBox.information(self, "导出完成", msg)

    # ---------- 历史记录 ----------

    def open_history(self):
        if self._history is None:
            QMessageBox.warning(self, "历史记录", "历史库不可用，详情见日志")
            return
        HistoryDialog(self._history, self).exec()

    # ---------- 按码重命名 ----------

    def rename_by_code(self):
        entries = [(self.file_list.item(i).data(Qt.UserRole),
                    self.results.get(self.file_list.item(i).data(Qt.UserRole), []))
                   for i in range(self.file_list.count())]
        if not entries:
            QMessageBox.information(self, "按码重命名", "列表为空")
            return
        dialog = RenameDialog(entries, skip_dir=self._clipboard_dir, parent=self)
        if not dialog.exec():
            return
        plan = dialog.plan
        ok, failures = execute_rename(plan)
        # 同步内部状态：路径映射 旧 -> 新
        renamed = {str(i.old_path): str(i.new_path) for i in plan.actionable}
        for old, new in renamed.items():
            if old in self.results:
                self.results[new] = self.results.pop(old)
            if old in self.errors:
                self.errors[new] = self.errors.pop(old)
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = item.data(Qt.UserRole)
            if path in renamed:
                new_path = renamed[path]
                item.setData(Qt.UserRole, new_path)
                item.setToolTip(new_path)
                item.setText(item.text().replace(Path(path).name, Path(new_path).name, 1))
        self._rebuild_table()
        self._refresh_template_preview()
        self._save_settings()  # 会话列表同步新路径
        logger.info("按码重命名完成: 成功 %d，失败 %d", ok, len(failures))

        notes = []
        multi = sum(1 for i in plan.items if not i.skipped and i.extra_codes)
        if multi:
            notes.append(f"{multi} 个图含多个码，已取第一个码命名")
        skipped = [i for i in plan.items if i.skipped]
        if skipped:
            notes.append(f"跳过 {len(skipped)} 个（" +
                         "；".join(sorted({i.skipped for i in skipped})) + "）")
        if failures:
            notes.append(f"失败 {len(failures)} 个: " +
                         "；".join(f"{p.name} ({err})" for p, err in failures))
        QMessageBox.information(
            self, "重命名完成",
            f"成功重命名 {ok} 个文件" + ("\n" + "\n".join(notes) if notes else ""))
