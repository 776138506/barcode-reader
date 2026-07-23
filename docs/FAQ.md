# 常见问题（FAQ）

## Windows 双击/运行无法启动

按顺序排查：

1. **Python 没装或没进 PATH**：「命令提示符」里运行 `py --version` 或 `python --version`，报"不是内部或外部命令"说明没装或安装时没勾「Add python.exe to PATH」——重新安装并勾选（见 README 快速开始第 0 步）
2. **用了从别的系统复制的 `.venv`**：虚拟环境是**平台专用**的——从 Mac/Linux 复制的 `.venv` 在 Windows 上必挂。删掉 `.venv`，按 README 第 1 步在本机重建
3. **依赖缺失**（报 `ModuleNotFoundError`，如 numpy）：`.venv` 建错了环境或安装被中断，重新执行 `.venv\Scripts\python -m pip install -r requirements.txt`
4. **闪退看不到错误**：在「命令提示符」里运行 `.venv\Scripts\python main.py`，错误会打印在窗口里；日志见 `%LOCALAPPDATA%\BarcodeReader\logs\`

## Windows Smart App Control / SmartScreen 拦截

打包产物未签名，Windows 可能拦截：

- **SmartScreen 蓝色提示「Windows 已保护你的电脑」**：点「更多信息」→「仍要运行」
- **从网络下载的 exe 被锁定**：右键 exe →「属性」→ 勾选「解除锁定」→「确定」，再双击
- **Smart App Control（Win11）提示「无法验证发布者」**：「设置 → 隐私和安全性 → Windows 安全中心 → 应用和浏览器控制 → Smart App Control 设置」，临时调低或把本应用加入信任；长期方案是开发者签名 + 公证

## 杀毒软件误报

PyInstaller 打包的 exe 是"自解压加载器"形态，部分杀软启发式误报：

- 用**默认单目录模式**打包（`python build.py`，不加 `--onefile`）可显著降低误报率
- 把项目目录/产物目录加入杀软白名单
- 产物是自己从源码构建的，源码完全可审计

## 打包注意事项与验证标准

- **不能交叉编译**：Windows 产物在 Windows 上打，macOS 产物在 macOS 上打，Linux 同理
- 先装开发依赖：`pip install -r requirements-dev.txt`（含 PyInstaller）
- 产物：`dist/BarcodeReader.app`（macOS）/ `dist/BarcodeReader/`（Windows/Linux 单目录）或 `--onefile` 单文件
- 图标占位：`icon.ico`（Windows）/ `icon.icns`（macOS）/ `icon.png`（Linux）放项目根目录自动启用
- **验证标准**：offscreen 启动存活 ≥10s、启动日志无「翻译文件加载失败」警告、能识别一张测试图
- 各平台已知事项：Windows 单文件 exe 首次启动慢（自解压）；macOS 未签名 .app 需在「隐私与安全性」放行，分发要签名+公证；Linux onefile 依赖目标机 glibc 版本（在较旧发行版上打包兼容性更好）

## Linux 启动报 libGL / xcb 错误

PySide6 需要 X11/GL 系统库。Debian/Ubuntu：

```bash
sudo apt install libgl1 libegl1 libxkbcommon0 libdbus-1-3 \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0
```

无显示环境（CI/服务器）可用 `QT_QPA_PLATFORM=offscreen` 运行测试与冒烟。

## 界面语言与对话框

- 界面全中文：启动时加载 Qt 自带 `qtbase_zh_CN` 翻译；`QFileDialog` 用 Qt 控件对话框（`DontUseNativeDialog`）保证三平台一致中文——原生对话框跟随系统语言，英文系统下会变英文
- 拖放文件没反应？把文件拖到**窗口任意位置**都可以（子控件不拦截，主窗口统一处理）；macOS 上请拖本地文件，某些应用的"拖出"不是文件 URL

## 其他

- **图片里有中文路径/文件名能识别吗**：能，图片读取走 Pillow 宽字符 API，三平台均支持非 ASCII 路径
- **识别不了的图怎么办**：把档位切到「极限」重试；仍不行的图欢迎提供给项目作为真实验证集（见 `docs/PROJECT-STATE.md` 待用户输入）
