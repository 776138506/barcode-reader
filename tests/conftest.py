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
