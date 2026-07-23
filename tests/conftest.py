"""pytest 共享辅助：测试用 tmp store 注入（不碰真实用户数据目录，AGENTS 纪律）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402


@pytest.fixture
def stores(tmp_path):
    """注入用 tmp 档案池/模板池。用法：MainWindow(..., **stores)"""
    return {
        "profile_store": ProfileStore(tmp_path / "profiles.json"),
        "template_store": TemplateStore(tmp_path / "templates.json"),
    }


@pytest.fixture(autouse=True)
def _gc_between_tests():
    """每个测试后强制 GC。

    测试创建的窗口 close() 后不删除（未设 WA_DeleteOnClose），信号 lambda
    形成的引用环使其驻留；累积约百个隐藏窗口后 Qt offscreen 在
    processEvents 中 Bus error/Segfault（实测复现）。逐测 GC 打断引用环。
    """
    import gc
    yield
    gc.collect()
