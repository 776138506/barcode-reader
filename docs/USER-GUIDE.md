# 使用手册

批量条码/二维码识别导出工具的功能详情与配置参考。快速上手见根目录 `README.md`，常见问题见 `docs/FAQ.md`。

## 功能详情

- **批量导入**：拖拽（主窗口任意位置）或文件对话框添加图片、文件夹，自动递归收集
- **剪贴板粘贴**：「粘贴图片」按钮或 Ctrl/Cmd+V
  - 剪贴板是**图片数据**（截图、复制的图像）：保存为 PNG 到会话临时目录（`系统临时目录/barcode-reader-clipboard-*`），随后进入与拖入完全相同的解码流程；临时图在窗口关闭时清理，且**不写入**持久化的最近会话列表（一次性产物）
  - 剪贴板是**文件 URL**（从 Finder/资源管理器复制的文件）或**路径文本**（每行一个路径）：解析后按 `add_paths` 流程添加
  - 无可识别内容时状态栏提示；Windows 截图的 DIB 格式由 Qt `QClipboard.image()` 归一化为 QImage（macOS 已验证，Windows 依 Qt 文档未实机验证）
- **多码识别**：一张图含多个码时全部识别，识别在后台线程执行不卡界面，带进度条
- **结果表格**：序号 / 文件名 / 码制 / 内容（默认行号表头已隐藏），单击行定位预览并高亮对应框，支持复制选中/全部内容（带条数与字符数反馈）
- **识别框标记（F2/F3）**：主预览每个框旁标注 `N: 内容`（疑似 `N?: 内容`，>24 字符截断），半透明底色块保证亮暗图可读；点击结果行对应框橙色加粗、其余变淡，点击空白/切图恢复
- **独立预览窗口（F1）**：双击预览区或文件列表打开（非模态、随选择跟随）；工具栏 适应窗口/100%/放大/缩小/左旋/右旋，滚轮缩放、拖拽平移；「显示标记」开关切换原图 ↔ 框+标注
- **去重视图**：勾选后按码内容去重，每个唯一码一行（序号/次数/码制/内容/来源文件），悬停看完整路径；去重模式下导出走去重记录，`{count}` 渲染次数、`{filename}` 渲染来源列表
- **历史记录库（SQLite）**：每次解码成功自动写入（字段：时间戳、文件名、码制、内容、来源路径），写入失败只记日志不影响主流程；左上角「历史…」按内容关键词搜索、载入历史来源图（源文件已删会提示）、复制内容。数据库位置：macOS `~/Library/Application Support/BarcodeReader/history.db`、Windows `%LOCALAPPDATA%\BarcodeReader\data\history.db`、Linux `$XDG_DATA_HOME/barcode-reader/data/history.db`
- **按码重命名**：左上角「按码重命名…」，确认对话框可改文件名模板（默认 `{content}`）并实时预览 旧名→新名；非法字符 `/\:*?"<>|` 替换下划线、重名自动加 `_N`、一图多码取第一个码（有提示）；粘贴的临时图一律跳过（一次性产物）；成功项同步列表/表格/会话，失败项单项跳过并汇总

## 模板与导出（两段式）

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

**两段式结构**：行模板（逐码渲染）→ 组内按**连接符**拼接 → **外模板**包装（`{items}` 为必填占位符，其余字符全部按字面输出，引号/花括号不需要转义）→ 组间换行。**分组**：不分组 / 按图片分组 / 全局聚合。外模板为 `{items}` 且不分组时等价逐行行为。

- 典型用例：行模板 `{content}` + 连接符 `','` + 外模板 `{'{items}'}` + 按图片分组 → `{'abc','def'}`
- **导出模板池**：模板行下拉切换命名模板（整套配置），「存为模板」入库（`数据目录/templates.json`）；内置预设：默认逐行、元组聚合、JSON 数组、SQL IN（首次运行写入，可删）
- 导出格式：TXT（两段式整篇）/ CSV（`utf-8-sig` + `newline=""`）/ XLSX（openpyxl）/ JSON（结构化数组，分组时嵌套 `{"group": 键, "items": [...]}`）
- **导出过滤**（「导出设置…」内，作用于导出与复制，不影响界面结果）：码制多选、内容长度范围、前缀、正则，可组合；正则无效时导出前弹警告
- **「复制到剪贴板」按钮**：按当前模板+过滤渲染后直接进系统剪贴板，状态栏提示条数与字符数
- 未知行占位符原样保留并警告，不崩溃

## 支持的码制

由 zxing-cpp 提供：矩阵码 QR Code（含 Micro QR、rMQR）/ Data Matrix / Aztec / PDF417（含 Compact/Micro）/ MaxiCode；一维码 Code 128、Code 39（含扩展）、Code 93、Codabar、ITF/ITF-14；零售码 EAN-13、EAN-8、UPC-A、UPC-E、DataBar 系列；DX Film Edge 等。

## 识别管线 v2

`decoder.py` 分层管线（对外接口 `decode_image/decode_images` 不变）：

- **PRE**：>20MP 大图先等比降采样到约 8MP；L0 之后的增强尝试在 ≤2MP 工作图上进行
- **L0 快速**：原图 + zxingcpp 默认参数
- **L1 增强**（命中即停）：GlobalHistogram → CLAHE → UnsharpMask 锐化 → ±15° 细旋转 → 1.5x/2x 放大 → gamma（0.5/2.0）
- **L2 组合**：binarizer × 增强 × 旋转角，硬上限 12 组
- **L3 区域层**（仅极限档，D19）：L2/L3 不命中即停，收集全部命中做**签名共识**——同一（内容 + 原图位置 80px 内）聚类需 ≥2 个不同参数签名才算有效，单签名降级为疑似码（防激进变换产出校验能过的假码）。8 条 40% 重叠横带粗切，tile 内 3x/4x 放大 → UnsharpMask(3,150,2) → ±10° 步进 1° × FixedThreshold/GlobalHistogram；横带全落空跑 3×3 网格兜底矩阵码；组合上限 750。耗时：命中场景约 12s/张，全 miss 约 20s/张（worker 线程承担）
- CLAHE 为纯 numpy 实现（不用 OpenCV 的原因见 `DECISIONS.md` D02）
- `DecodeResult.strategy` 记录命中信息；`decode_image_detailed()` 返回全部尝试记录；命中 position 按变换链反变换回原图坐标系（zxing 复核偏差 <2px）

### 识别参数档案池（D20）

识别设置行「档案」下拉 +「参数…」+「删除」：DecodeProfile 把管线全部参数结构化为可编辑档案（PRE/L1/L2/L3/共识五组，全开放可编辑 + 恢复默认），内置「默认」不可删改（编辑需另存），用户档案存 `数据目录/profiles.json`。档位与档案**正交**：档位管进到第几层，档案管每层参数。

Profile schema 全字段：`pre`(max_pixels/downscale_target/work_pixels)；`l1`(binarizers/clahe_clip/clahe_tiles/sharpen/angles/upscales/gammas)；`l2`(binarizers/enhancers/angles/max_combos)；`l3`(bands/band_overlap/grid/grid_overlap/scales/sharpen/angle_min/angle_max/band_step/grid_step/binarizers/max_combos)；`consensus`(min_signatures/dist)。

### 识别控制项（底部设置行，均持久化）

- **档位**：快速（仅 PRE+L0）/ 均衡（到 L1，默认）/ 极限（全层）
- **码制白名单**：「码制…」勾选 10 种码制（默认全选）
- **疑似码**：默认启用，`return_errors=True` 捞回校验失败且文本非空的码；表格码制列带 `?`、浅黄底；**疑似码不写入历史库正式记录**（过程数据仍在 strategy_log）
- **单图增强重扫**：文件列表右键，强制极限档重识该图，不影响其他图

### strategy_log 表（history.db）

| 字段 | 内容 |
| --- | --- |
| `ts` | ISO 时间戳 |
| `image_sha256` | 源文件内容哈希 |
| `features` | JSON：brightness/contrast/blur/width/height/aspect/rotation_est |
| `attempts` | JSON 数组：每层的 `{layer, desc, hit, ms}` |
| `final_strategy` | 命中策略（未命中为空串） |
| `final_hit_count` | 最终码数量（0 = 未识别） |

## 状态与日志

### 状态持久化（QSettings）

组织名/应用名均为 `BarcodeReader`（macOS `~/Library/Preferences/`，Windows 注册表，Linux `~/.config/`）。保存的键：

| 键 | 内容 |
| --- | --- |
| `ui/geometry` | 主窗口几何/尺寸 |
| `export/template` | 导出行模板文本 |
| `export/joiner` / `export/outer` / `export/group_by` | 两段式连接符/外模板/分组 |
| `export/format` / `export/delimiter` | 导出格式 / CSV 分隔符 |
| `export/filter_*` | 导出过滤（types/min_len/max_len/prefix/regex） |
| `export/template_name` | 模板池当前选中名 |
| `export/last_dir` | 最近使用的导出目录 |
| `decode/tier` / `decode/formats` / `decode/suspect` / `decode/profile` | 档位/码制白名单/疑似码/识别档案 |
| `session/recent_images` | 最近会话的图片路径列表（启动恢复，已删除文件自动跳过） |

保存时机：窗口关闭时全量保存；导出成功后立即保存导出相关键。

### 日志

标准 `logging`，`RotatingFileHandler`：主文件 1MB + 3 个轮滚备份，同时输出到控制台。日志目录：macOS `~/Library/Logs/BarcodeReader/`、Windows `%LOCALAPPDATA%\BarcodeReader\logs\`、Linux `$XDG_STATE_HOME/barcode-reader/logs/`。记录：启动/退出、添加图片数量、每张图解码结果与耗时、批量失败汇总、导出路径与条数、错误堆栈。左上角「打开日志目录」直接打开。

### 全局异常兜底

`sys.excepthook` 接管未捕获异常：完整堆栈写入日志（CRITICAL），并弹出错误对话框，不再静默崩溃。

### 配置损坏保护（D26）

数据目录的 profiles/templates JSON 损坏时：自动备份为 `<原名>.corrupt-<时间戳>.bak`（原文件留证可抢救），回落默认并一次性弹窗提示；写库失败会弹警告。

## 开发

```bash
# 重新生成测试图
.venv/bin/python tests/gen_test_images.py
# 单元测试（当前 121 个）
.venv/bin/python -m pytest tests/ -q
# GUI 冒烟（无头）
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/smoke_gui.py
```

测试图：`manifest.json` 9 张基础图 + `hard_manifest.json` 6 张合成疑难图（噪声独立种子可复现）+ `real_manifest.json` 真实药品追溯码图（5/5 验收，slow 标记约 12s）。备选解码方案：无 zxing-cpp wheel 的平台可退回 `pyzbar`（需系统 zbar）。

## 已知限制

- 极端模糊、强反光或严重畸变的实拍图可能仍无法识别
- 导出 CSV/XLSX 的表头目前固定为 `序号,文件名,码制,内容`
- 识别结果不做内容去重：同一张图重复添加会被忽略，不同图含相同码各自列出
