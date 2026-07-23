# BarcodeReader 项目说明

批量识别图片中条码/二维码并按自定义模板导出的跨平台桌面工具（Windows / macOS / Linux）。

## 技术栈与关键决策

- GUI：PySide6；解码：zxing-cpp（`read_barcodes` 一次返回图中所有码）；图像处理：Pillow + numpy
- **识别管线 v2**（`decoder.py`）：PRE 降采样（>20MP→约 8MP）→ L0 默认参数 → L1 增强（GlobalHistogram/CLAHE/UnsharpMask 锐化/±15° 细旋转/1.5x/2x/gamma，命中即停）→ L2 组合（binarizer 含 FixedThreshold，上限 12 组）→ **L3 区域层**（仅极限档：8 横带 40% 重叠粗切，tile 内 3x/4x+UnsharpMask(3,150,2)+±10° 步进 1°×ft/gh，横带落空再 3×3 网格兜底，上限 750 组）；L1/L2 在 ≤2MP 工作图上跑（常量 `MAX_PIXELS/DOWNSCALE_TARGET_PIXELS/WORK_PIXELS/MAX_L2_COMBOS/MAX_L3_COMBOS`）；**L2/L3 签名共识误识防护**（内容+位置 80px 聚类 ≥2 不同参数签名才有效，单签名降 suspect）；`DecodeResult.strategy` 记命中层+参数+耗时；`decode_image_detailed()` 返回全部 attempts；命中 position 按变换链（scale/rot/offset）反变换回原图坐标系（`_invert_point`/`_forward_point`）；控制项：`tier`(fast/balanced/max)、`formats`（`formats_flag(显示名列表)`→`barcode_formats_from_str`）、`include_suspect`（return_errors 疑似码，空文本错误结果丢弃，`suspect=True` 不写历史正式记录）
- **不使用 OpenCV**：与 PyInstaller 冻结导入器存在结构性冲突（cv2 bootstrap 二次 import 死循环），且 Windows 下 `cv2.imread` 无法读非 ASCII 路径。预处理（灰度/均衡/CLAHE/缩放/旋转/gamma）一律用 Pillow + numpy 实现
- 模板导出：`exporter.py` 两段式管线（行模板 → 组内连接符拼接 → 外模板 `{items}` 字面替换 → 组间换行）；行占位符 `{index}/{filename}/{type}/{content}/{count}/{date}/{time}`（`{count}` 供去重导出），未知占位符原样保留并 `warnings.warn`，不得抛异常；**外模板不走 format 解析**，除 `{items}` 外全按字面输出；分组 `none/image/global`；格式 TXT/CSV/XLSX(openpyxl)/JSON；`ExportFilter.types` 存 zxing **短名**（与 `DecodeResult.format` 一致，显示名经 `FORMAT_WHITELIST` 映射）；过滤正则用 `re.error` 包装成 ValueError

## 环境与命令

```bash
source .venv/bin/activate        # 所有依赖只装进 .venv，禁止污染系统 Python
python main.py                   # 运行
pytest tests/ -q                 # 测试（当前 98 个，含 1 个 ~12s 的 slow 真实图验收）
QT_QPA_PLATFORM=offscreen python tests/smoke_gui.py   # 无头 GUI 冒烟
python build.py                  # PyInstaller 打包（不能交叉编译，须在目标平台执行）
```

## 跨平台纪律（修改代码时必须遵守）

- 路径一律 `pathlib`，禁止字符串拼 `/`；文件读写显式 `encoding="utf-8"`
- TXT 导出 `newline=None`（跟随平台换行）；CSV `newline=""` + `utf-8-sig`（Excel 兼容）
- 引入新依赖前确认其在 win_amd64 / macosx / manylinux 均有官方 wheel

## 状态与日志约定

- 持久化一律走 QSettings（组织/应用名均为 `BarcodeReader`，常量见 `paths.py`）；`MainWindow(settings=None, history_db=None, profile_store=None, template_store=None)` 支持注入临时 ini/tmp store，**测试不得碰真实用户配置与数据目录**（测试一律注入 tmp store，见 `tests/conftest.py` 与各 `_stores()`）
- 日志用 `logging_setup.py`（RotatingFileHandler 1MB×3 + 控制台），目录选址逻辑在 `paths.py`；新增模块如有错误路径，用 `logger.exception` 记堆栈
- 未捕获异常由 `main.py` 的 `sys.excepthook` 兜底，不要在业务代码里裸 `except: pass`

## UI 约定

- 拖放统一由 MainWindow 的 dragEnterEvent/dropEvent 处理；**所有子控件（含 viewport）必须 `setAcceptDrops(False)`**，否则 QListWidget/QTableWidget 默认拦截 drop 事件导致拖拽失效
- 中文界面：`main.py` 启动时安装 `qtbase_zh_CN` + `qt_zh_CN` 翻译（QTranslator 需持有引用）；QFileDialog 一律传 `DontUseNativeDialog`（原生对话框跟随系统语言，无法保证中文）；新增 UI 文案一律中文
- 测试用 QMimeData 构造 urls 直接调用事件处理函数模拟拖放（见 `tests/test_dragdrop.py` / `tests/smoke_gui.py`）
- `PreviewLabel.show_image` 加载失败必须清空旧 pixmap 并显示提示——残留上一张图会被用户当成"预览失效/串图"（回归测试 `tests/test_preview.py`）
- **对话框高度必须考虑小屏幕**：内容多的自定义对话框一律用 `ui/scroll_helper.py` 的 `wrap_scrollable()`（内容进 QScrollArea、按钮栏固定在外）+ `cap_dialog_height()`（上限 = 光标所在屏可用高度 × 0.8）；新增对话框对照 `tests/test_dialogs.py` 补断言
- **标记帧统一走 `ui/preview_window.py` 的 Frame 模型**：主预览（PreviewLabel）与 F1 窗口共用 `build_frames/frame_color/frame_label/frame_state`——绿框有效、黄框疑似（序号带 `?`）、橙框点击高亮、其余变淡（alpha 60）；框序号 = 结果表格「序号」列（跨图累加，`MainWindow._frames_for()`）；结果表格垂直行号表头一律隐藏（与「序号」列重复）
- **调试脚本不得对 `tests/images/` 里的原始测试图执行重命名等破坏性操作**——重命名只对 tmp 副本进行（曾有调试脚本把 qr_hello.png 改名导致测试图缺失）

## 结构

```
main.py / decoder.py / exporter.py / history.py / renamer.py / paths.py / logging_setup.py
profiles.py                # DecodeProfile 档案池（profiles.json）
templates.py               # 导出模板池（templates.json + 内置预设）
ui/main_window.py          # 主窗口：文件列表、预览高亮、结果表格（含去重视图）、模板编辑、导出、识别设置行（档案/档位/码制/疑似码）
ui/profile_dialog.py       # 识别参数档案编辑（PRE/L1/L2/L3/共识 全开放，QScrollArea 小屏适配）
ui/preview_window.py       # F1 独立预览窗口 + 标记帧模型（Frame/编号/配色/高亮，主预览共用）
ui/scroll_helper.py        # 对话框小屏适配（QScrollArea 包装 + 高度上限）
ui/history_dialog.py       # 历史记录面板（SQLite 搜索/载入/复制）
ui/rename_dialog.py        # 按码重命名确认对话框（模板 + 预览）
ui/export_settings_dialog.py  # 导出设置（两段式 + 过滤）
ui/formats_dialog.py       # 码制白名单勾选对话框
tests/                     # pytest + gen_test_images.py + smoke_gui.py
build.py                   # PyInstaller 打包脚本
```

- 历史库：`history.py`（SQLite，`records` 表：时间戳/文件名/码制/内容/来源路径；`strategy_log` 表：ts/image_sha256/features(JSON)/attempts(JSON)/final_strategy/final_hit_count，库文件在 `paths.data_dir()`）；写入失败只记日志不得影响主流程；`MainWindow(history_db=None)` 支持注入 tmp 库
- 重命名：`renamer.py` 纯逻辑（非法字符 `/\:*?"<>|`→`_`、重名加 `_N`、多码取首码），GUI 只负责确认与状态同步；剪贴板临时目录内的图一律跳过重命名

## 修改守则

- 改完必须重跑 `pytest tests/ -q` 和 offscreen 冒烟，全绿才算完成
- 界面/结构/约定变化时同步更新 README.md 和本文件
- **新决策点（选型、弃项、变通）必须追加到 `docs/DECISIONS.md`**，禁止修改历史条目；每轮工作结束更新 `docs/PROJECT-STATE.md` 的当前状态与排队清单
