"""一键打包脚本（PyInstaller）。

在目标平台上运行（PyInstaller 不支持交叉编译）：

    python build.py            # 按当前平台生成对应产物
    python build.py --onefile  # 强制单文件模式

产物：
    Windows : dist/BarcodeReader/BarcodeReader.exe（--onefile 时为 dist/BarcodeReader.exe）
    macOS   : dist/BarcodeReader.app
    Linux   : dist/BarcodeReader/BarcodeReader（--onefile 时为 dist/BarcodeReader）

图标占位：将 icon.ico（Windows）/ icon.icns（macOS）/ icon.png（Linux）
放到项目根目录即可自动启用；没有则使用默认图标。
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

# Windows CI 控制台默认 cp1252，中文输出会 UnicodeEncodeError（D41 原则：
# CLI 脚本内重配置 UTF-8）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "BarcodeReader"

ICON_BY_PLATFORM = {
    "Windows": "icon.ico",
    "Darwin": "icon.icns",
    "Linux": "icon.png",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="PyInstaller 一键打包")
    parser.add_argument("--onefile", action="store_true",
                        help="单文件模式（默认 macOS 生成 .app，其他平台为单目录）")
    args = parser.parse_args()

    system = platform.system()
    if system not in ICON_BY_PLATFORM:
        print(f"不支持的平台: {system}", file=sys.stderr)
        return 1

    import importlib.util
    if importlib.util.find_spec("PyInstaller") is None:
        pip = ".venv\\Scripts\\python" if system == "Windows" else ".venv/bin/python"
        print("错误: 未安装 PyInstaller（打包工具在开发依赖里）。\n"
              f"请先执行: {pip} -m pip install -r requirements-dev.txt",
              file=sys.stderr)
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",          # 无控制台窗口（GUI 模式）
        "--name", APP_NAME,
        # zxing-cpp 的 nanobind 扩展与数据文件需要一起收集
        "--collect-all", "zxingcpp",
    ]

    # Qt 简体中文翻译（qtbase_zh_CN）：PyInstaller 钩子收集的翻译目录位置
    # 在冻结环境下 QLibraryInfo 不一定指得到，显式打入一份兜底（D24）。
    # 不打 qt_zh_CN.qm：它是引用 qtmultimedia 的元目录，包内无 Multimedia。
    from PySide6.QtCore import QLibraryInfo
    trans_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    sep = ";" if system == "Windows" else ":"
    for qm in ("qtbase_zh_CN.qm",):
        src = trans_dir / qm
        if src.exists():
            cmd += ["--add-data", f"{src}{sep}PySide6/Qt/translations"]
        else:
            print(f"警告: 未找到翻译文件 {qm}，打包后 Qt 对话框可能显示英文")

    cmd.append(str(ROOT / "main.py"))

    icon = ROOT / ICON_BY_PLATFORM[system]
    if icon.exists():
        cmd += ["--icon", str(icon)]
    else:
        print(f"提示: 未找到 {icon.name}，使用默认图标（可参考 build.py 注释添加占位图标）")

    if args.onefile:
        cmd.append("--onefile")

    print("运行:", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)

    dist = ROOT / "dist"
    if system == "Darwin":
        app = dist / f"{APP_NAME}.app"
        print(f"\n打包完成: {app}" if app.exists() else "\n打包完成，请查看 dist/ 目录")
    else:
        print(f"\n打包完成，产物在 {dist}/ 目录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
