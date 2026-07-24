"""入口：QApplication + MainWindow，日志初始化与全局异常兜底。"""
import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logging_setup import setup_logging  # noqa: E402
from paths import APP_NAME, ORG_NAME  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

logger = logging.getLogger(__name__)


def _install_zh_translators(app: QApplication) -> list[QTranslator]:
    """加载 Qt 自带简体中文翻译（qtbase/qt），让 QFileDialog 等 Qt 原生
    控件显示中文。返回 translator 列表（调用方需持有引用防 GC）。

    打包（PyInstaller）后 QLibraryInfo 指向的 Frameworks 目录可能没有
    全部 .qm（--add-data 的文件会落到 Resources），故按候选目录逐个尝试。"""
    candidates = [QLibraryInfo.path(QLibraryInfo.TranslationsPath)]
    if getattr(sys, "frozen", False):  # PyInstaller 冻结环境
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(
            str(exe_dir / ".." / "Resources" / "PySide6" / "Qt" / "translations"))
    translators = []
    # 只加载 qtbase（承载 QFileDialog/QMessageBox 等我们用到的全部控件翻译）。
    # 不加载 qt_zh_CN：它是 99 字节的元目录，仅引用 qtbase + qtmultimedia，
    # 打包后 qtmultimedia 不在包内会导致 load 失败，而本应用不用 Multimedia。
    for name in ("qtbase_zh_CN",):
        translator = QTranslator(app)
        for path in candidates:
            if translator.load(name, path):
                app.installTranslator(translator)
                translators.append(translator)
                break
        else:
            logger.warning("Qt 翻译文件加载失败: %s (已尝试: %s)", name, candidates)
    return translators


def _excepthook(exc_type, exc_value, exc_tb):
    """未捕获异常：写日志（含堆栈）并弹窗，避免静默崩溃。"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logger.critical("未捕获异常:\n%s",
                    "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    try:
        QMessageBox.critical(None, "程序错误",
                             f"发生未处理的错误，详情见日志。\n\n{exc_type.__name__}: {exc_value}")
    except Exception:  # noqa: BLE001 - GUI 不可用也不能再抛
        pass


def main() -> int:
    setup_logging()
    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationName(APP_NAME)
    sys.excepthook = _excepthook

    app = QApplication(sys.argv)
    _translators = _install_zh_translators(app)  # noqa: F841 - 持有引用防 GC
    logger.info("应用启动 (Python %s, %s)", sys.version.split()[0], sys.platform)
    win = MainWindow()
    win.show()
    code = app.exec()
    # 优雅停机：退出前给后台 worker 一个收尾窗口，避免解释器关闭时
    # worker emit 撞到已删除的 signals（D41）
    from PySide6.QtCore import QThreadPool
    if not QThreadPool.globalInstance().waitForDone(3000):
        logger.warning("退出时仍有后台解码任务未完成（已强制结束）")
    logger.info("应用退出，退出码 %d", code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
