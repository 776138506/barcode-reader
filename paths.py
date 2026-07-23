"""跨平台路径选址与 QSettings 组织/应用名。

日志目录手写三平台选址，不引入 platformdirs 新依赖：
三个平台各一行，逻辑透明且无额外打包体积。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ORG_NAME = "BarcodeReader"
APP_NAME = "BarcodeReader"


def log_dir() -> Path:
    """按平台惯例返回日志目录（不保证已创建）。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME / "logs"
    # Linux 及其他 Unix：遵循 XDG Base Directory（state）
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "barcode-reader" / "logs"


def data_dir() -> Path:
    """按平台惯例返回应用数据目录（历史库等，不保证已创建）。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME / "data"
    # Linux 及其他 Unix：遵循 XDG Base Directory（data）
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "barcode-reader" / "data"
