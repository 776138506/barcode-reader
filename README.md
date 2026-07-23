# 批量条码/二维码识别导出工具

跨平台桌面应用（Windows / macOS / Linux）：拖入多张图片，批量识别其中的条码/二维码，按自定义模板导出。

## 功能亮点

- **全码制识别**：QR / Code 128 / EAN / Data Matrix / PDF417 / Aztec 等，一图多码全部命中
- **分层识别管线**：L0 直读 → L1 增强 → L2 组合 → L3 区域扫描，疑难图（倾斜/模糊/反光/低对比）逐层救回，真实药品追溯码 5/5 命中
- **两段式模板导出**：行模板 + 连接符 + 外模板 + 分组，TXT/CSV/XLSX/JSON，元组、SQL IN 等格式自由拼
- **识别框可视化**：全局编号标注、疑似码黄色标记、点击高亮、独立预览窗口（缩放/旋转/平移）
- **识别参数全开放**：档位 + 可编辑参数档案池，误识有签名共识防护
- **开箱体验**：剪贴板粘贴识别、去重计数、历史库、按码重命名、全中文界面、状态/模板自动记忆

## 技术栈

PySide6（GUI）+ zxing-cpp（解码，纯 pip wheel）+ Pillow/numpy（图像处理）。
不用 OpenCV：与 PyInstaller 冻结导入器结构性冲突，决策见 `docs/DECISIONS.md` D02。

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

先装开发依赖（`pip install -r requirements-dev.txt`），再执行 `python build.py`（Windows 用 `.venv\Scripts\python build.py`），产出的 `.exe` / `.app` **自带全部依赖、不需要装 Python**，拷给任何人双击即用。注意**不能交叉编译**，必须在目标平台上打包；注意事项与验证标准见 `docs/FAQ.md`。

## 文档地图

| 文档 | 内容 |
| --- | --- |
| `docs/USER-GUIDE.md` | 使用手册：功能详情、模板与导出语法、识别管线与控制项、状态与日志 |
| `docs/FAQ.md` | 常见问题：Windows 无法启动、Smart App Control/杀毒拦截、打包、Linux 依赖、界面中文化 |
| `docs/DECISIONS.md` | 决策日志：每个技术选择的背景、弃项与后果（D01–D28） |
| `docs/PROJECT-STATE.md` | 项目状态：当前进度、路线图、排队清单 |
| `AGENTS.md` | 项目约定：结构、命令、开发纪律（面向维护者/AI 助手） |
