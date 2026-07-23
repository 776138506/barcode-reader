"""识别控制项测试：档位、码制白名单、疑似码、单图增强重扫。"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from decoder import (FORMAT_WHITELIST, decode_image, decode_image_detailed,  # noqa: E402
                     formats_flag)
from history import History  # noqa: E402
from ui import main_window as mw  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    return mw.MainWindow(settings=settings, history_db=tmp_path / "h.db", **_stores(tmp_path))


def _damaged_qr(tmp_path) -> Path:
    """挖掉一块的 QR：zxing 只能作为校验失败的疑似码捞回。"""
    with Image.open(IMG_DIR / "qr_hello.png") as img:
        arr = np.asarray(img.convert("L")).copy()
    arr[140:180, 140:180] = 255
    out = tmp_path / "damaged.png"
    Image.fromarray(arr).save(out)
    return out


# ---------- 档位 ----------

def test_tier_fast_vs_balanced():
    """快速档只跑 PRE+L0：易图照样中，难图救不回；均衡档能救回。"""
    easy, att = decode_image_detailed(IMG_DIR / "qr_hello.png", tier="fast")
    assert easy and len(att) == 1 and att[0].layer == "L0"

    hard_fast, att_f = decode_image_detailed(IMG_DIR / "hard_blur.png", tier="fast")
    assert not [r for r in hard_fast if not r.suspect]
    assert all(a.layer in ("PRE", "L0") for a in att_f)  # 没有跑 L1/L2

    hard_bal, _ = decode_image_detailed(IMG_DIR / "hard_blur.png", tier="balanced")
    assert any(r.content == "HARD-BLUR-01" for r in hard_bal)


def test_tier_invalid_raises():
    with pytest.raises(ValueError):
        decode_image_detailed(IMG_DIR / "qr_hello.png", tier=" turbo")


# ---------- 码制白名单 ----------

def test_formats_whitelist():
    qr_only = formats_flag(["QR Code"])
    no_qr = formats_flag(["Code 128", "EAN-13"])
    assert decode_image(IMG_DIR / "qr_hello.png", formats=qr_only)
    assert not decode_image(IMG_DIR / "qr_hello.png", formats=no_qr)
    # Code128 白名单不影响对应码制
    assert decode_image(IMG_DIR / "code128_a.png", formats=no_qr)
    # 全选 / None = 不限制
    assert formats_flag(list(FORMAT_WHITELIST)) is None
    assert formats_flag(None) is None
    assert formats_flag([]) is None


def test_formats_persist(qapp, tmp_path):
    win = _make_window(tmp_path)
    win._format_names = ["QR Code"]
    win.tier_combo.setCurrentIndex(0)  # fast
    win.suspect_check.setChecked(False)
    win._save_settings()
    win.close()

    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win2 = mw.MainWindow(settings=settings, history_db=tmp_path / "h2.db", **_stores(tmp_path))
    assert win2._format_names == ["QR Code"]
    assert win2.tier_combo.currentData() == "fast"
    assert not win2.suspect_check.isChecked()
    win2.close()


# ---------- 疑似码 ----------

def test_suspect_marks_and_toggle(tmp_path):
    damaged = _damaged_qr(tmp_path)
    with_s = decode_image(damaged, include_suspect=True, tier="fast")
    assert with_s and all(r.suspect for r in with_s)
    assert with_s[0].format == "QRCode"

    without_s = decode_image(damaged, include_suspect=False, tier="fast")
    assert not without_s


def test_suspect_gui_marks_and_history_filter(qapp, tmp_path):
    damaged = _damaged_qr(tmp_path)
    db = tmp_path / "h.db"
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=db, **_stores(tmp_path))
    win.add_paths([str(damaged)])
    win._pool.waitForDone(30000)
    qapp.processEvents()

    assert win.table.rowCount() == 1
    assert win.table.item(0, 2).text().endswith("?")
    bg = win.table.item(0, 3).background().color()
    assert bg.red() == 255 and bg.green() == 248  # 浅黄底
    # 疑似码不写入正式历史记录
    assert History(db).count() == 0
    # 但 strategy_log 有过程数据且 final_hit_count=0
    logs = History(db).strategy_logs()
    assert len(logs) == 1 and logs[0]["final_hit_count"] == 0
    win.close()


# ---------- 单图增强重扫 ----------

def test_rescan_only_affects_target(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=tmp_path / "h.db", **_stores(tmp_path))
    win.tier_combo.setCurrentIndex(0)  # 快速档：hard_blur 识不出
    hard = str(IMG_DIR / "hard_blur.png")
    easy = str(IMG_DIR / "qr_hello.png")
    win.add_paths([hard, easy])
    win._pool.waitForDone(30000)
    qapp.processEvents()
    assert not [r for r in win.results[hard] if not r.suspect]
    easy_before = list(win.results[easy])

    # 对 hard_blur 右键增强重扫（极限档）
    for i in range(win.file_list.count()):
        if win.file_list.item(i).data(0x0100) == hard:
            win.rescan_item(win.file_list.item(i))
            break
    win._pool.waitForDone(60000)
    qapp.processEvents()
    assert any(r.content == "HARD-BLUR-01" for r in win.results[hard])
    assert win.results[easy] == easy_before  # 另一张图不受影响
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}
