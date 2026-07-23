"""日志测试：日志文件确实写入，RotatingFileHandler 配置正确。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging_setup  # noqa: E402
from logging_setup import setup_logging  # noqa: E402
from paths import log_dir  # noqa: E402


def _reset_logging():
    """清理 root logger 与模块幂等标记，保证测试独立。"""
    root = logging.getLogger()
    for h in root.handlers[:]:
        h.close()
        root.removeHandler(h)
    logging_setup._initialized = False


def test_log_file_written(tmp_path):
    _reset_logging()
    directory = setup_logging(tmp_path)
    assert directory == tmp_path

    logging.getLogger("test").info("冒烟日志消息-utf8-中文")
    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "barcode-reader.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "冒烟日志消息-utf8-中文" in content

    # RotatingFileHandler 参数：1MB × (1 主文件 + 3 轮滚)
    from logging.handlers import RotatingFileHandler
    rotating = [h for h in logging.getLogger().handlers
                if isinstance(h, RotatingFileHandler)]
    assert rotating and rotating[0].maxBytes == 1024 * 1024
    assert rotating[0].backupCount == 3
    # 控制台输出保留
    assert any(isinstance(h, logging.StreamHandler)
               and not isinstance(h, RotatingFileHandler)
               for h in logging.getLogger().handlers)
    _reset_logging()


def test_log_dir_per_platform():
    """日志目录按平台惯例选址（本机 macOS 验证实际路径，其余平台验证函数可调用）。"""
    directory = log_dir()
    assert directory.is_absolute()
    if sys.platform == "darwin":
        assert directory == Path.home() / "Library" / "Logs" / "BarcodeReader"
    elif sys.platform.startswith("win"):
        assert directory.name == "logs" and "BarcodeReader" in str(directory)
    else:
        assert "barcode-reader" in str(directory) and directory.name == "logs"
