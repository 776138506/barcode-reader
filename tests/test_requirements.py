"""依赖声明完整性检查：防止「代码直接 import 但 requirements.txt 未声明」。

Windows 全新环境曾因 numpy 漏声明无法启动（2026-07-23），此测试固化防线。
扫描项目根与 ui/ 下 .py 文件的顶层 import，凡第三方包必须出现在
requirements.txt 或 requirements-dev.txt 中（含包名映射）。
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# import 名 → PyPI 包名（仅第三方；未列入的非 stdlib 名视为项目内模块则跳过）
THIRD_PARTY = {
    "PySide6": "PySide6",
    "zxingcpp": "zxing-cpp",
    "PIL": "Pillow",
    "numpy": "numpy",
    "openpyxl": "openpyxl",
    "pytest": "pytest",
    "PyInstaller": "pyinstaller",
}

PROJECT_MODULES = {
    "decoder", "exporter", "history", "logging_setup", "paths",
    "profiles", "renamer", "templates", "ui", "main", "build",
}


def _declared() -> set[str]:
    pkgs: set[str] = set()
    for req in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / req).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_.-]+?)\s*(?:[>=<!\[]|$)", line)
            if m and not line.strip().startswith("#"):
                pkgs.add(m.group(1).lower())
    return pkgs


def _imports() -> set[str]:
    found: set[str] = set()
    for py in list(ROOT.glob("*.py")) + list((ROOT / "ui").glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_third_party_imports_declared():
    declared = _declared()
    missing = []
    for mod in sorted(_imports()):
        if mod in PROJECT_MODULES or mod in sys.stdlib_module_names:
            continue
        pkg = THIRD_PARTY.get(mod)
        if pkg is None:
            missing.append(f"{mod}（未知第三方包，需加入 THIRD_PARTY 映射或确认）")
        elif pkg.lower() not in declared:
            missing.append(f"{mod}（对应包 {pkg} 未在 requirements 中声明）")
    assert not missing, "未声明的第三方依赖: " + ", ".join(missing)
