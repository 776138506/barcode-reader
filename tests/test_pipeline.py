"""识别管线 v2 测试：疑难图命中率对比、strategy 字段、strategy_log、特征提取。"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
import zxingcpp  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from decoder import (attempts_to_dicts, decode_image,  # noqa: E402
                     decode_image_detailed, extract_features)
from history import History  # noqa: E402
from ui import main_window as mw  # noqa: E402
from profiles import ProfileStore  # noqa: E402
from templates import TemplateStore  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"
HARD = json.loads((IMG_DIR / "hard_manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _l0_hit(path: Path, expect: str) -> bool:
    """只跑 L0（zxingcpp 默认参数，对应旧行为的直读路径）。"""
    with Image.open(path) as im:
        return any(b.valid and b.text == expect
                   for b in zxingcpp.read_barcodes(im.convert("RGB")))


def test_hard_images_pipeline_vs_l0():
    """合成疑难图：管线必须全部命中且不差于 L0，打印分层命中对比。"""
    l0_hits = pipe_hits = 0
    print("\n疑难图分层命中对比:")
    for name, expect in sorted(HARD.items()):
        l0_ok = _l0_hit(IMG_DIR / name, expect)
        results, attempts = decode_image_detailed(IMG_DIR / name)
        pipe_ok = any(r.content == expect for r in results)
        l0_hits += l0_ok
        pipe_hits += pipe_ok
        strat = results[0].strategy if results else "未命中"
        print(f"  {name:<22} L0={'✓' if l0_ok else '✗'} 管线={'✓' if pipe_ok else '✗'} {strat}")
        assert pipe_ok, f"{name}: 管线未能救回"
    print(f"  合计: L0 {l0_hits}/{len(HARD)} -> 管线 {pipe_hits}/{len(HARD)}")
    assert pipe_hits >= l0_hits
    assert pipe_hits == len(HARD)


def test_strategy_field():
    """strategy 记录命中层与耗时；易图 L0 命中，难图 L1/L2 命中。"""
    easy = decode_image(IMG_DIR / "qr_hello.png")
    assert easy and easy[0].strategy.startswith("L0:")
    assert "ms" in easy[0].strategy

    results, attempts = decode_image_detailed(IMG_DIR / "hard_blur.png")
    assert results and results[0].strategy.startswith(("L1:", "L2:"))
    # attempts 完整记录：第一条是 L0 且未命中，每条都有 layer/desc/hit/ms
    assert attempts[0].layer == "L0" and attempts[0].hit == 0
    for a in attempts_to_dicts(attempts):
        assert set(a) == {"layer", "desc", "hit", "ms"}
        assert isinstance(a["ms"], float) and a["ms"] >= 0
    # 命中 attempt 的 hit 数与结果数一致
    assert attempts[-1].hit == len(results)


def test_big_image_downscale_path():
    """>20MP 大图：attempts 第一条是 PRE 降采样记录。"""
    results, attempts = decode_image_detailed(IMG_DIR / "hard_big.png")
    assert results, "大图应经降采样后命中"
    assert attempts[0].layer == "PRE" and "downscale" in attempts[0].desc


def test_extract_features():
    """特征提取：字段齐全、类型与范围正确。"""
    with Image.open(IMG_DIR / "qr_hello.png") as img:
        f = extract_features(img.convert("RGB"))
    assert set(f) == {"brightness", "contrast", "blur", "width", "height",
                      "aspect", "rotation_est"}
    assert 0 <= f["brightness"] <= 255
    assert f["contrast"] >= 0
    assert f["blur"] >= 0
    assert f["width"] > 0 and f["height"] > 0
    assert f["aspect"] == pytest.approx(f["width"] / f["height"], rel=1e-2)
    assert -45.0 <= f["rotation_est"] <= 45.0
    # 白底 QR 图亮度应偏高
    assert f["brightness"] > 200


def test_strategy_log_written(qapp, tmp_path):
    """GUI 解码完成后 strategy_log 落库，attempts 结构正确。"""
    db = tmp_path / "history.db"
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win = mw.MainWindow(settings=settings, history_db=db, **_stores(tmp_path))
    win.add_paths([str(IMG_DIR / "qr_hello.png")])
    win._pool.waitForDone(30000)
    qapp.processEvents()

    logs = History(db).strategy_logs()
    assert len(logs) == 1
    entry = logs[0]
    assert len(entry["image_sha256"]) == 64
    assert entry["final_hit_count"] == 1
    assert entry["final_strategy"].startswith("L0:")
    assert isinstance(entry["attempts"], list) and entry["attempts"]
    first = entry["attempts"][0]
    assert set(first) == {"layer", "desc", "hit", "ms"}
    assert first["layer"] == "L0" and first["hit"] == 1
    assert entry["features"]["width"] > 0
    win.close()


def _stores(tmp_path):
    """tmp store 注入：测试不碰真实用户数据目录（AGENTS 纪律）。"""
    return {"profile_store": ProfileStore(tmp_path / "profiles.json"),
            "template_store": TemplateStore(tmp_path / "templates.json")}
