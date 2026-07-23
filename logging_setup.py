"""日志初始化：RotatingFileHandler 落盘 + 控制台输出。

主日志文件 1MB，保留 3 个轮滚备份（共 4 个文件，约 4MB 上限）。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from paths import log_dir

_MAX_BYTES = 1024 * 1024
_BACKUP_COUNT = 3
_initialized = False


def setup_logging(log_directory: Path | None = None) -> Path:
    """初始化全局 logging，返回实际使用的日志目录。重复调用幂等。"""
    global _initialized
    directory = Path(log_directory) if log_directory else log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    if _initialized:
        return directory

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        directory / "barcode-reader.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    _initialized = True
    logging.getLogger(__name__).info("日志初始化完成: %s", directory)
    return directory
