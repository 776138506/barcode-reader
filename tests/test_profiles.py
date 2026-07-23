"""参数化档案池 + 导出模板池测试。"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from decoder import (Attempt, DecodeProfile, DecodeResult, _consensus_results,  # noqa: E402
                     _l3_tiles, decode_image_detailed)
from profiles import BUILTIN_NAME, ProfileStore  # noqa: E402
from templates import BUILTIN_TEMPLATES, TemplateStore  # noqa: E402
from ui import main_window as mw  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"


def _stores(tmp_path):
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}


def _hit(content, cx, cy, sig):
    r = DecodeResult(content=content, format="Code128",
                     position=[(cx, cy), (cx + 10, cy), (cx + 10, cy + 10), (cx, cy + 10)])
    return r, Attempt(layer="L3", desc=f"combo-{sig}", hit=1, ms=1.0), sig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------- DecodeProfile 序列化 ----------

def test_profile_json_roundtrip():
    p = DecodeProfile()
    p2 = DecodeProfile.from_dict(json.loads(json.dumps(p.to_dict())))
    assert p2.to_dict() == p.to_dict()
    # 缺字段容忍
    p3 = DecodeProfile.from_dict({"l3": {"bands": 5}})
    assert p3.l3.bands == 5 and p3.consensus.min_signatures == 2


# ---------- 自定义 profile 实际作用到管线 ----------

def test_custom_consensus_threshold_applies():
    """共识阈值改成 3：双签名命中被降级为疑似。"""
    out2 = _consensus_results([_hit("A", 0, 0, "s1"), _hit("A", 1, 1, "s2")], [],
                              DecodeProfile().consensus)
    assert not out2[0].suspect
    strict = DecodeProfile()
    strict.consensus.min_signatures = 3
    out3 = _consensus_results([_hit("A", 0, 0, "s1"), _hit("A", 1, 1, "s2")], [],
                              strict.consensus)
    assert out3[0].suspect


def test_custom_bands_applies():
    p = DecodeProfile()
    assert len(_l3_tiles(100, 100, p.l3)) == 8
    p.l3.bands = 5
    assert len(_l3_tiles(100, 100, p.l3)) == 5


def test_custom_l1_upscales_in_attempts(tmp_path):
    """自定义 L1 放大倍率集出现在 attempts 描述里（空白图全层跑完）。"""
    from PIL import Image
    blank = tmp_path / "blank.png"
    Image.new("RGB", (200, 100), (255, 255, 255)).save(blank)
    p = DecodeProfile()
    p.l1.upscales = [3.0]
    _results, attempts = decode_image_detailed(blank, profile=p)
    descs = [a.desc for a in attempts]
    assert "upscale-3.0x" in descs
    assert "upscale-1.5x" not in descs


def test_custom_l2_max_combos():
    p = DecodeProfile()
    p.l2.max_combos = 2
    p.l1.angles = []       # 清空 L1 角度项加速
    p.l1.upscales = []
    p.l1.gammas = []
    _results, attempts = decode_image_detailed(IMG_DIR / "hard_rot15.png",
                                               tier="max", profile=p)
    l2 = [a for a in attempts if a.layer == "L2"]
    assert len(l2) == 2


def test_default_profile_matches_constants():
    """默认 profile 与模块常量一致（零变化的 schema 级证据）。"""
    import decoder
    p = DecodeProfile()
    assert p.pre.max_pixels == decoder.MAX_PIXELS
    assert p.pre.downscale_target == decoder.DOWNSCALE_TARGET_PIXELS
    assert p.pre.work_pixels == decoder.WORK_PIXELS
    assert p.l2.max_combos == decoder.MAX_L2_COMBOS
    assert p.l3.max_combos == decoder.MAX_L3_COMBOS


# ---------- ProfileStore ----------

def test_profile_store_crud_and_persist(tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    assert store.names() == [BUILTIN_NAME]
    p = DecodeProfile()
    p.consensus.min_signatures = 3
    store.save("严格", p)
    assert store.get("严格").consensus.min_signatures == 3
    # 内置不可写/不可删
    with pytest.raises(ValueError):
        store.save(BUILTIN_NAME, DecodeProfile())
    with pytest.raises(ValueError):
        store.delete(BUILTIN_NAME)
    store.rename("严格", "很严格")
    assert "很严格" in store.names() and "严格" not in store.names()
    # 持久化往返
    store2 = ProfileStore(tmp_path / "profiles.json")
    assert store2.get("很严格").consensus.min_signatures == 3
    store2.delete("很严格")
    assert store2.names() == [BUILTIN_NAME]
    # 内置可"恢复"（get 永远是纯默认）
    assert store2.get(BUILTIN_NAME).to_dict() == DecodeProfile().to_dict()


# ---------- TemplateStore ----------

def test_template_store_presets_and_crud(tmp_path):
    store = TemplateStore(tmp_path / "templates.json")
    for name in ("默认逐行", "元组聚合", "JSON 数组", "SQL IN"):
        assert store.get(name) is not None
    assert store.get("元组聚合")["outer"] == "{'{items}'}"
    cfg = dict(BUILTIN_TEMPLATES["默认逐行"])
    cfg["template"] = "{content}"
    store.save("我的", cfg)
    assert store.get("我的")["template"] == "{content}"
    store.rename("我的", "你的")
    store2 = TemplateStore(tmp_path / "templates.json")
    assert store2.get("你的") is not None
    store2.delete("你的")
    assert store2.get("你的") is None


# ---------- GUI 集成 ----------

def test_gui_profile_switch_and_persist(qapp, tmp_path):
    stores = _stores(tmp_path)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=tmp_path / "h.db", **stores)
    # 新建 profile 并切换
    p = DecodeProfile()
    p.l3.bands = 6
    stores["profile_store"].save("六带", p)
    win._reload_profile_combo("六带")
    assert win._decode_options()["profile"].l3.bands == 6
    win._save_settings()
    win.close()

    win2 = mw.MainWindow(settings=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat),
                         history_db=tmp_path / "h2.db", **stores)
    assert win2.profile_combo.currentText() == "六带"
    assert win2._decode_options()["profile"].l3.bands == 6
    win2.close()


def test_gui_template_pool_switch(qapp, tmp_path):
    stores = _stores(tmp_path)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=tmp_path / "h.db", **stores)
    # 切到内置「元组聚合」：配置实际应用到 UI 状态
    win.tpl_pool_combo.setCurrentText("元组聚合")
    qapp.processEvents()
    assert win.template_edit.text() == "{content}"
    assert win._joiner == "','"
    assert win._outer == "{'{items}'}"
    assert win._group_by == "image"
    # 当前配置存为新模板
    win._templates.save("自定义", win._current_export_config())
    assert win._templates.get("自定义")["joiner"] == "','"
    win.close()
