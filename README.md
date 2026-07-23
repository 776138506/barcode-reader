# 批量条码/二维码识别导出工具

跨平台桌面应用（Windows / macOS / Linux）：拖入多张图片，批量识别其中的条码/二维码，按自定义模板导出 TXT / CSV。

## 功能

- 拖拽（或文件对话框）批量添加图片、文件夹，自动递归收集图片——主窗口任意位置均可拖入（子控件不拦截，统一由主窗口处理）
- **剪贴板粘贴**：「粘贴图片」按钮或 Ctrl/Cmd+V——截图/复制的图像直接粘贴识别；从 Finder/资源管理器复制的文件（URL 或路径文本）也可粘贴添加
- 一张图含多个码时全部识别，预览图上绿框高亮位置
- 识别在后台线程执行，批量处理不卡界面，带进度条
- 结果表格：序号 / 文件名 / 码制 / 内容，单击行定位预览，支持复制选中/全部内容（默认行号表头已隐藏，与「序号」列去重）
- **识别框标记（F2/F3）**：主预览每个框旁标注与表格一致的全局序号（疑似码黄框 + `?`）；点击结果行对应框变橙加粗、其余变淡，点击空白/切图恢复
- **独立预览窗口（F1）**：双击预览区或文件列表打开（非模态、随选择跟随）；工具栏 适应窗口/100%/放大/缩小/左旋/右旋，滚轮缩放、拖拽平移；「显示标记」开关切换原图 ↔ 框+序号
- **去重视图**：勾选后按码内容去重，每个唯一码一行，显示出现次数与来源文件列表；导出随视图走（去重导出用 `{count}` 占位符）
- **历史记录库（SQLite）**：解码结果自动落库，可按关键词搜索、载入历史来源图、复制内容
- **按码重命名**：按码内容批量重命名列表中的图片，确认前预览 旧名→新名，非法字符替换、重名自动加序号
- 自定义模板占位符导出 TXT 或 CSV，模板带实时预览（前 3 条渲染结果）
- **分层识别管线 v2**：L0 快速直读 → L1 增强（GlobalHistogram/CLAHE/±15° 细旋转/放大/gamma，命中即停）→ L2 极限组合（binarizer×增强×旋转，上限 12 组）；>20MP 大图先降采样；每个码记录命中策略（层+参数+耗时）；命中位置已反变换回原图坐标系，高亮框贴合
- **识别控制项**：三档（快速/均衡/极限）、码制白名单（10 种可勾选）、疑似码开关（校验失败码带 `?` + 浅黄底）、单图右键「增强重扫（极限档）」，均持久化
- **策略日志**：每次识别的图像特征（亮度/对比度/模糊度/主旋转角等）与全部尝试记录写入 SQLite `strategy_log` 表

## 技术选型

- GUI：PySide6
- 解码：[zxing-cpp](https://pypi.org/project/zxing-cpp/)（纯 pip 安装，无动态库依赖，码制支持全；一次调用返回图中所有码）
- 预处理：Pillow + numpy（图像读取/灰度/直方图均衡/缩放/旋转；zxing-cpp 可直接接收 PIL Image）

> 为什么不用 OpenCV：opencv-python(-headless) 的 `cv2/__init__.py` bootstrap 与
> PyInstaller 冻结导入器冲突（4.13/5.0 均复现 `recursion is detected during loading of "cv2"`），
> 打包产物无法启动。预处理需求用 Pillow 即可完整覆盖，且 Pillow 在 Windows 上
> 用宽字符 API 打开文件，中文/非 ASCII 路径天然兼容，故已移除 opencv 依赖。

> 备选方案：若目标机器 Python 版本无 zxing-cpp 预编译 wheel，可退回 `pyzbar`
>（需 `brew install zbar`）。本项目在 Python 3.14 上 zxing-cpp 3.1.0 可用，未启用备选。

## 快速开始（从零到跑起来）

> **换电脑必读**：虚拟环境（`.venv`）和打包产物都是**平台专用**的——
> 从 Mac 复制的 `.venv` 在 Windows 上不能用，macOS 的 `.app` 也不能在 Windows 上运行。
> 换机器后只需按下面步骤在新机器上重装一次（约 2 分钟），不用复制 `.venv`。

### 第 0 步：安装 Python（只需一次）

- **Windows**：到 [python.org/downloads](https://www.python.org/downloads/) 下载安装包，安装时**务必勾选「Add python.exe to PATH」**
- **macOS**:`brew install python`，或同样从 python.org 安装
- **Linux**：用系统包管理器安装 Python 3.11+（如 `sudo apt install python3 python3-venv`）

### 第 1 步：创建虚拟环境并安装依赖

**Windows**（在「命令提示符」或 PowerShell 中逐行执行）：

```bat
cd /d 项目所在目录\barcode-reader
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**macOS / Linux**（终端中逐行执行）：

```bash
cd 项目所在目录/barcode-reader
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

这三行的含义：进入项目目录 → 创建独立虚拟环境 `.venv` → 把依赖装进它（只影响本项目，不污染系统）。

### 第 2 步：运行

**Windows**：

```bat
.venv\Scripts\python main.py
```

**macOS / Linux**：

```bash
.venv/bin/python main.py
```

以后每次使用只需重复第 2 步。也可以做个双击启动器：Windows 新建 `启动.bat`，内容一行 `.venv\Scripts\python main.py`；macOS 新建 `启动.command`，内容 `cd "$(dirname "$0")" && .venv/bin/python main.py`（首次需 `chmod +x 启动.command`）。

### 想要免安装双击版？→ 打包

在自己电脑上执行一次 `python build.py`（见下文「打包」），产出的 `.exe` / `.app` **自带全部依赖、不需要装 Python**，拷给任何人双击即用。

## 依赖说明

所有依赖（zxing-cpp、PySide6、Pillow，间接依赖 numpy、openpyxl）在 Windows / macOS / Linux 三平台均有官方预编译 wheel（已核对 PyPI），直接 pip 安装即可，无需编译。

### 各平台注意事项

- **Linux**：PySide6 运行需要 X11/GL 系统库。若启动报 `libGL` / `xcb` 相关错误，Debian/Ubuntu 安装：
  ```bash
  sudo apt install libgl1 libegl1 libxkbcommon0 libdbus-1-3 \
      libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0
  ```
  无显示环境（CI）可用 `QT_QPA_PLATFORM=offscreen` 运行测试与冒烟。
- **macOS**：无需额外系统依赖；首次运行打包出的 .app 需在“系统设置 → 隐私与安全性”中允许（未签名）。
- **Windows**：无需额外系统依赖；图片读取走 Pillow（Windows 上使用宽字符 API 打开文件），**含中文/非 ASCII 字符的图片路径可正常识别**。

开发/测试依赖（pytest、PyInstaller 等，只想使用程序可不装）：

```bash
# macOS / Linux
.venv/bin/pip install -r requirements-dev.txt
# Windows
.venv\Scripts\pip install -r requirements-dev.txt
```

## 打包（PyInstaller）

**PyInstaller 不支持交叉编译：必须在目标平台上执行打包**（Windows 产物在 Windows 上打，macOS 产物在 macOS 上打，Linux 同理）。打包前先完成「快速开始」的第 1 步，并安装开发依赖（`requirements-dev.txt`，含 PyInstaller）。

```bash
# macOS / Linux
.venv/bin/python build.py            # 按当前平台生成产物
.venv/bin/python build.py --onefile  # 强制单文件模式

# Windows
.venv\Scripts\python build.py
.venv\Scripts\python build.py --onefile
```

产物：

| 平台    | 默认产物                                | `--onefile`               |
| ------- | --------------------------------------- | ------------------------- |
| Windows | `dist/BarcodeReader/BarcodeReader.exe`  | `dist/BarcodeReader.exe`  |
| macOS   | `dist/BarcodeReader.app`                | `dist/BarcodeReader`      |
| Linux   | `dist/BarcodeReader/BarcodeReader`      | `dist/BarcodeReader`      |

- 图标占位：把 `icon.ico`（Windows）/ `icon.icns`（macOS）/ `icon.png`（Linux）放到项目根目录即自动启用，缺省用默认图标。
- `build.py` 已内置 `--collect-all zxingcpp`（收集 nanobind 扩展与数据文件），并显式打入 `qtbase_zh_CN.qm` 中文翻译兜底（D24）。
- 打包后验证标准：offscreen 启动存活 ≥10s、日志无「翻译文件加载失败」警告。
- 各平台已知事项：
  - **Windows**：杀毒软件可能误报 PyInstaller 单文件产物，可用默认单目录模式规避；首次启动单文件 exe 较慢（需自解压）。
  - **macOS**：未签名 .app 分发后需在“隐私与安全性”中放行；如需分发到 Gatekeeper 默认放行的程度，要 Apple 开发者证书签名 + 公证。
  - **Linux**：onefile 产物依赖目标机器的 glibc 版本（在较旧发行版上打包兼容性更好）；同样受上文 X11/GL 系统库要求约束。


## 跨平台界面说明

- **全中文界面**：启动时用 `QTranslator` 加载 Qt 自带的 `qtbase_zh_CN` 翻译（只加载它：对话框/按钮翻译都在 qtbase；`qt_zh_CN` 是引用 qtmultimedia 的 99 字节元目录，打包后必加载失败且本应用不需要，见 D24）；`QFileDialog` 统一传 `DontUseNativeDialog`——原生系统对话框跟随系统语言（英文系统下会变英文），Qt 控件对话框 + 中文翻译可保证三平台一致的中文界面。
- **拖放**：主窗口级别统一处理 `dragEnterEvent`/`dropEvent`，文件列表、结果表格、预览区（含 viewport）均已关闭 `acceptDrops`，拖到窗口任意位置都会进入 `add_paths` 去重导入流程。

## 剪贴板粘贴

- 点击左上角「粘贴图片」按钮或按 **Ctrl+V（macOS 为 Cmd+V）**（`QKeySequence.Paste` 按平台映射）。
- 剪贴板是**图片数据**（截图、复制的图像）时：保存为 PNG 到会话临时目录（`系统临时目录/barcode-reader-clipboard-*`），随后进入与拖入图片完全相同的解码流程。临时图在窗口关闭时清理，且**不写入**持久化的最近会话列表（属一次性产物）。
- 剪贴板是**文件 URL**（从 Finder/资源管理器复制的文件）或**路径文本**（每行一个路径）时：解析后按现有 `add_paths` 流程添加。
- 剪贴板无可识别内容时状态栏提示「剪贴板中没有可识别的图片或文件路径」。
- 跨平台说明：Windows 截图在剪贴板中多为 DIB 格式，Qt 的 `QClipboard.image()` 已归一化为 `QImage`，本机 macOS 已验证，Windows 行为依 Qt 文档、未实机验证。

## 模板与导出（两段式，D16/D18）

**行模板占位符**（单码渲染）：

| 占位符       | 含义                     | 示例              |
| ------------ | ------------------------ | ----------------- |
| `{index}`    | 序号（全局递增，分组内不重启） | `1`          |
| `{filename}` | 来源文件名（去重记录为 `;` 连接的来源列表） | `a.png` |
| `{type}`     | 码制                     | `QRCode`          |
| `{content}`  | 码内容                   | `https://…`       |
| `{count}`    | 出现次数（去重记录 >1，普通记录恒为 1） | `2` |
| `{date}`     | 导出日期                 | `2026-07-22`      |
| `{time}`     | 导出时间                 | `09:30:15`        |

**两段式结构**：行模板（逐码渲染）→ 组内按**连接符**拼接 → **外模板**包装（`{items}` 为必填占位符，**其余字符全部按字面输出**，引号/花括号不需要转义）→ 组间换行。**分组**：不分组 / 按图片分组 / 全局聚合。外模板为 `{items}` 且不分组时等价旧逐行行为（向后兼容）。

- 典型用例：行模板 `{content}` + 连接符 `','` + 外模板 `{'{items}'}` + 按图片分组 → `{'abc','def'}`
- **导出模板池**：模板行下拉切换命名模板（行模板/连接符/外模板/分组/格式/分隔符/过滤整套配置），「存为模板」把当前配置命名入库（`数据目录/templates.json`），当前选中名进 QSettings；内置预设：默认逐行、元组聚合、JSON 数组、SQL IN（首次运行写入，可删）
- 导出格式：TXT（两段式整篇）/ CSV / XLSX（列渲染同 CSV 语义，openpyxl）/ JSON（结构化数组，分组时嵌套 `{"group": 键, "items": [...]}`）
- **导出过滤**（「导出设置…」内，作用于导出与复制，不影响界面结果）：码制多选、内容长度范围、前缀、正则，可组合；正则无效时导出前弹警告
- **「复制到剪贴板」按钮**：按当前模板+过滤渲染后直接进系统剪贴板，不落盘，状态栏提示条数
- 未知行占位符原样保留并警告，不崩溃；CSV `utf-8-sig` + `newline=""`；TXT 跟随平台换行

## 支持的码制

由 zxing-cpp 提供，主要包括：

- 矩阵码：QR Code（含 Micro QR、rMQR）、Data Matrix、Aztec、PDF417（含 Compact/Micro）、MaxiCode
- 一维码：Code 128、Code 39（含扩展）、Code 93、Codabar、ITF / ITF-14
- 零售码：EAN-13、EAN-8、UPC-A、UPC-E、DataBar 系列
- 其他：DX Film Edge 等

## 测试

```bash
# 重新生成测试图（QR/Code128/DataMatrix/EAN-13 单码图、多码图、旋转图、低质量图）
.venv/bin/python tests/gen_test_images.py

# 单元测试：解码断言码数/内容/码制；导出断言占位符渲染（含未知占位符不崩溃）
.venv/bin/python -m pytest tests/ -q

# GUI 冒烟（无头）：建窗口 → 批量识别 → 校验表格/预览/模板预览/导出文件
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/smoke_gui.py
```

测试图片由 zxing-cpp 自带的 `create_barcode` 生成（整数倍缩放保证条宽均匀），无需额外的 libdmtx 等系统库。

## 项目结构

```
barcode-reader/
├── main.py                  # 入口：QApplication + MainWindow + 日志/excepthook
├── decoder.py               # 解码核心：多码制识别 + 预处理重试（Pillow 读取兼容非 ASCII 路径）
├── exporter.py              # 模板渲染 + TXT/CSV 导出（含 {count} 占位符）
├── history.py               # SQLite 历史记录库
├── renamer.py               # 按码重命名纯逻辑（非法字符/冲突/多码取首码）
├── paths.py                 # QSettings 组织/应用名 + 三平台日志/数据目录选址
├── logging_setup.py         # RotatingFileHandler + 控制台日志初始化
├── build.py                 # PyInstaller 一键打包（按当前平台生成产物）
├── ui/
│   ├── main_window.py       # 主窗口（列表/预览/表格/去重/模板/导出/QSettings）
│   ├── history_dialog.py    # 历史记录面板（搜索/载入/复制）
│   └── rename_dialog.py     # 重命名确认对话框（模板 + 预览）
├── requirements.txt         # 运行依赖
├── requirements-dev.txt     # 测试/打包依赖
└── tests/
    ├── gen_test_images.py   # 生成测试图 + manifest.json
    ├── test_decoder.py      # 解码断言
    ├── test_exporter.py     # 模板/导出断言
    ├── test_settings.py     # QSettings 持久化断言
    ├── test_logging.py      # 日志落盘断言
    ├── test_clipboard.py    # 剪贴板粘贴断言
    ├── test_dedup.py        # 去重视图与 {count} 断言
    ├── test_history.py      # 历史库写入/搜索/容错断言
    ├── test_rename.py       # 重命名（非法字符/冲突/多码/跳过）断言
    ├── test_dragdrop.py     # 拖放链路断言（QDropEvent 模拟）
    ├── test_preview.py      # 预览定位/高亮框/失败不残留断言
    ├── test_pipeline.py     # 管线 v2：疑难图命中率/strategy/strategy_log/特征
    ├── test_position.py     # 坐标反变换精度（标记实证 + zxing 复核）
    ├── test_controls.py     # 档位/白名单/疑似码/增强重扫
    ├── test_export_v2.py    # R1：两段式/兼容/XLSX/JSON/过滤/剪贴板
    ├── test_real_image.py   # 真实难图验收（5/5 + 误识防护 + 共识单测）
    └── smoke_gui.py         # GUI 无头冒烟
```

测试图：`manifest.json` 9 张基础图（零回归断言）+ `hard_manifest.json` 6 张合成疑难图（高斯模糊/±15° 旋转/低对比/渐变反光/反色/>20MP 大图，调参目标为 L0 打不下、管线能救回；噪声用独立种子保证可复现）+ `real_manifest.json` 真实药品追溯码图（5 个 Code128，极限档验收 5/5 + 误识拦截，`tests/test_real_image.py` 标记 slow 约 12s）。

## 识别管线 v2

`decoder.py` 分层管线（对外接口 `decode_image/decode_images` 不变）：

- **PRE**：>20MP 大图先等比降采样到约 8MP；L0 之后的增强尝试在 ≤2MP 工作图上进行（控制纯 numpy 增强算子成本）
- **L0 快速**：原图 + zxingcpp 默认参数
- **L1 增强**（命中即停）：binarizer=GlobalHistogram → CLAHE 局部对比度增强 → ±15° 细旋转（服务一维条码）→ 1.5x/2x 放大 → gamma 校正（0.5/2.0）
- **L2 极限**：binarizer × 增强 × 旋转角组合空间，硬上限 12 组
- **CLAHE 为纯 numpy 实现**（分块裁剪直方图均衡 + 块间双线性插值，按行分块控内存）；不用 OpenCV 的原因见其 bootstrap 与 PyInstaller 冻结导入器的结构性冲突（「技术选型」节）

`DecodeResult.strategy` 记录命中信息（如 `L1:clahe, 12.3ms`）；`decode_image_detailed()` 额外返回全部尝试记录（含未命中场景）。命中后 `position` 按记录的变换链（降采样倍率/旋转角/放大倍率/tile 偏移）反变换回原图坐标系（旋转以图中心为原点，已对 PIL rotate(expand=True) 实证，zxing 复核偏差 <2px）。

**L3 区域层**（仅极限档，D19）：L1 未命中后，L2/L3 不再命中即停，而是收集全部命中做**签名共识**——同一（内容 + 原图位置 80px 内）聚类需 ≥2 个不同参数签名（放大/锐化/角度/binarizer）才算有效，单签名降级为疑似码（防激进变换产出校验能过的假码）。L3 用 8 条 40% 重叠横带粗切（一维码条带不被切断），tile 内 3x/4x 放大 → UnsharpMask(3,150,2) → ±10° 步进 1° 旋转扫描 × FixedThreshold/GlobalHistogram；横带全落空才跑 3×3 网格兜底矩阵码；组合硬上限 750。耗时：命中场景约 12s/张，全 miss 扫描约 20s/张（worker 线程承担）。

### 识别参数档案池（D20）

识别设置行的「档案」下拉 +「参数…」+「删除」：**DecodeProfile** 把管线全部参数结构化为可编辑档案（PRE/L1/L2/L3/共识五组，全开放可编辑 + 恢复默认），内置「默认」档案不可删、不可改（编辑需另存为新名），用户档案存 `数据目录/profiles.json`，当前选中名进 QSettings。档位（快速/均衡/极限）与档案**正交**：档位管进到第几层，档案管每层参数。

Profile schema 全字段：

- `pre`: max_pixels / downscale_target / work_pixels
- `l1`: binarizers(la/gh/ft/bool) / clahe_clip / clahe_tiles / sharpen(半径,百分比,阈值) / angles / upscales / gammas
- `l2`: binarizers / enhancers(clahe,gamma0.6) / angles / max_combos
- `l3`: bands / band_overlap / grid / grid_overlap / scales / sharpen / angle_min / angle_max / band_step / grid_step / binarizers / max_combos
- `consensus`: min_signatures / dist

### 识别控制项（底部设置行，均 QSettings 持久化）

- **档位**：快速（仅 PRE+L0）/ 均衡（到 L1，默认）/ 极限（全层）；decoder 接口 `tier` 参数
- **码制白名单**：「码制…」对话框勾选 10 种码制（默认全选），映射 `zxingcpp.barcode_formats_from_str`
- **疑似码**：默认启用，每层 `return_errors=True` 捞回校验失败且文本非空的码；表格中码制列带 `?`、浅黄底。**疑似码不写入历史库正式记录**（保持 records 表"确认结果"语义；过程数据仍在 strategy_log，`final_hit_count` 只计有效码）
- **单图增强重扫**：文件列表右键「增强重扫（极限档）」，强制 max 档重识该图并刷新结果，不影响其他图

### strategy_log 表（history.db）

| 字段              | 内容                                                         |
| ----------------- | ------------------------------------------------------------ |
| `ts`              | ISO 时间戳                                                   |
| `image_sha256`    | 源文件内容哈希                                               |
| `features`        | JSON：brightness/contrast/blur/width/height/aspect/rotation_est |
| `attempts`        | JSON 数组：每层的 `{layer, desc, hit, ms}`                   |
| `final_strategy`  | 命中策略（未命中为空串）                                     |
| `final_hit_count` | 最终码数量（0 = 未识别）                                     |

## 去重 / 历史 / 重命名

### 去重视图

结果表格上方勾选「去重视图」：相同码内容合并为一行，列为 序号 / 次数 / 码制 / 内容 / 来源文件（`;` 连接，悬停看完整路径）。去重模式下导出走去重后的记录，`{count}` 渲染出现次数，`{filename}` 渲染来源列表；取消勾选恢复逐码视图，行为不变。

### 历史记录库（SQLite）

每次解码成功自动写入 SQLite 历史库（字段：时间戳、文件名、码制、内容、来源路径），写入失败只记日志、不影响主流程。数据库位置（`paths.data_dir()`）：

- macOS：`~/Library/Application Support/BarcodeReader/history.db`
- Windows：`%LOCALAPPDATA%\BarcodeReader\data\history.db`
- Linux：`$XDG_DATA_HOME/barcode-reader/data/history.db`（默认 `~/.local/share/...`）

左上角「历史…」打开历史面板：按内容关键词搜索（留空显示全部，按时间倒序）、把选中记录的来源图重新载入结果表格（源文件已删除的会提示）、复制选中内容。

### 按码重命名

左上角「按码重命名…」：对当前列表图片按码内容批量重命名。确认对话框内可改文件名模板（复用占位符机制，默认 `{content}`，可含 `{index}` `{type}` 等），下方实时预览 旧名→新名 与备注。规则：

- 非法字符 `/\:*?"<>|` 替换为下划线，首尾点/空格剔除，全空回退 `unnamed`
- 重名冲突自动追加 `_2`、`_3`…
- 一图多码取第一个码（预览和完成汇总中提示）
- **粘贴的剪贴板临时图一律跳过**：它是一次性产物，重命名后路径逃出临时目录会破坏「不持久化 + 退出清理」的语义
- 成功项同步更新文件列表、结果表格与 QSettings 会话列表；失败项（权限/占用）单项跳过并在完成对话框汇总

## 状态与日志

### 状态持久化（QSettings）

组织名/应用名均为 `BarcodeReader`（存储位置由 Qt 按平台惯例决定：macOS `~/Library/Preferences/`，Windows 注册表，Linux `~/.config/`）。保存的键：

| 键                    | 内容                                       |
| --------------------- | ------------------------------------------ |
| `ui/geometry`         | 主窗口几何/尺寸                            |
| `export/template`     | 导出行模板文本                             |
| `export/joiner`       | 两段式连接符                               |
| `export/outer`        | 两段式外模板                               |
| `export/group_by`     | 分组维度（`none`/`image`/`global`）        |
| `export/format`       | 导出格式（`TXT`/`CSV`/`XLSX`/`JSON`）      |
| `export/delimiter`    | CSV 分隔符（`,` 或 `\t`）                  |
| `export/filter_*`     | 导出过滤（types/min_len/max_len/prefix/regex） |
| `export/last_dir`     | 最近使用的导出目录                         |
| `session/recent_images` | 最近会话的图片路径列表（启动时直接恢复，已删除的文件自动跳过） |

保存时机：窗口关闭时全量保存；导出成功后立即保存导出相关键。分隔符选择 Tab 时，导出 CSV 会把模板中的逗号列分隔替换为 Tab（占位符内不含逗号，替换安全）。

### 日志

标准 `logging`，`RotatingFileHandler`：主文件 1MB，保留 3 个轮滚备份（`barcode-reader.log` + `.1/.2/.3`），同时输出到控制台。日志目录按平台惯例选址（`paths.py` 手写三行实现，未引入 platformdirs——三个平台各一行、逻辑透明、不增加依赖与打包体积）：

- macOS：`~/Library/Logs/BarcodeReader/`
- Windows：`%LOCALAPPDATA%\BarcodeReader\logs\`
- Linux：`$XDG_STATE_HOME/barcode-reader/logs/`（默认 `~/.local/state/barcode-reader/logs/`）

记录的关键事件：应用启动/退出、添加图片数量、每张图解码结果与耗时、导出路径与条数、错误堆栈（含未捕获异常）。窗口左上角「打开日志目录」按钮可直接在文件管理器中打开日志目录。

### 全局异常兜底

`sys.excepthook` 接管未捕获异常：完整堆栈写入日志（CRITICAL 级），并弹出错误对话框提示，不再静默崩溃。

## 已知限制

- 极端模糊、强反光或严重畸变的实拍图可能仍无法识别（重试策略不能覆盖所有情况）
- 导出 CSV 的表头目前固定为 `序号,文件名,码制,内容`
- 识别结果不做去重：同一张图重复添加会被忽略，但不同图含相同码会各自列出
