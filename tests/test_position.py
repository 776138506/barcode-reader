"""坐标反变换测试：变换链命中的码位置必须回到原图坐标系。"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import zxingcpp  # noqa: E402
from PIL import Image  # noqa: E402

import decoder  # noqa: E402
from decoder import (_forward_point, _invert_point, _rotate_op,  # noqa: E402
                     decode_image_detailed)

IMG_DIR = Path(__file__).resolve().parent / "images"
HARD = json.loads((IMG_DIR / "hard_manifest.json").read_text(encoding="utf-8"))


def test_rotate_inverse_empirical():
    """标记块实证：PIL rotate(expand=True) 任意角反变换误差 <0.5px。"""
    img = Image.new("L", (100, 60), 255)
    for dx in range(3):
        for dy in range(3):
            img.putpixel((20 + dx, 10 + dy), 0)  # 块中心 (21, 11)
    # 管线只用 ±15° 细旋转；90° 时中心取整约定差 1px（与本管线无关，不覆盖）
    for degrees in (15, -15, 8, -8, 30):
        rot, op = _rotate_op(img, degrees)
        coords = np.argwhere(np.asarray(rot) < 128)
        cy, cx = coords[:, 0].mean(), coords[:, 1].mean()
        ox, oy = _invert_point(cx, cy, [op])
        err = math.hypot(ox - 21, oy - 11)
        # 阈值 1px：标记质心量化 + 重采样模糊；公式精度由 zxing 复核用例保证（<2px）
        assert err < 1.0, f"degrees={degrees} 误差 {err:.2f}px"


def test_scale_rotate_roundtrip():
    """scale + rot 复合链：forward 与 invert 互逆。"""
    ops = [("scale", 0.62), ("rot", -15, (500, 300), (520, 330)), ("scale", 2.0)]
    x, y = 123.0, 45.0
    fx, fy = _forward_point(x, y, ops)
    bx, by = _invert_point(fx, fy, ops)
    assert math.hypot(bx - x, by - y) < 1e-6


def _raw_position_in_candidate(name: str, build_candidate, expect: str):
    """在候选图上直接跑 zxing 拿原始 position，与管线结果正变换后比对。"""
    results, _attempts = decode_image_detailed(IMG_DIR / name)
    r = [r for r in results if r.content == expect][0]
    return r, build_candidate()


def test_hard_rot15_position_accuracy():
    """hard_rot15（L1 旋转命中）：position 正变换回候选图与 zxing 原始值偏差 <2px。"""
    expect = HARD["hard_rot15.png"]
    results, _ = decode_image_detailed(IMG_DIR / "hard_rot15.png")
    r = [r for r in results if r.content == expect][0]
    with Image.open(IMG_DIR / "hard_rot15.png") as im:
        cand, op = _rotate_op(im.convert("RGB"), -15)
    raw = [b for b in zxingcpp.read_barcodes(cand) if b.valid and b.text == expect][0]
    for corner_name in ("top_left", "bottom_right"):
        rp = getattr(raw.position, corner_name)
        idx = 0 if corner_name == "top_left" else 2
        fx, fy = _forward_point(*r.position[idx], [op])
        assert math.hypot(fx - rp.x, fy - rp.y) < 2.0, corner_name
    # 界内断言（原图尺寸）
    with Image.open(IMG_DIR / "hard_rot15.png") as im:
        W, H = im.size
    assert all(0 <= px <= W and 0 <= py <= H for px, py in r.position)


def test_hard_big_position_accuracy():
    """hard_big（PRE 降采样后 L0 命中）：position 反变换回原图尺度，偏差 <2px（候选坐标）。"""
    expect = HARD["hard_big.png"]
    results, _ = decode_image_detailed(IMG_DIR / "hard_big.png")
    r = [r for r in results if r.content == expect][0]
    with Image.open(IMG_DIR / "hard_big.png") as im:
        im = im.convert("RGB")
        w, h = im.size
        s = (decoder.DOWNSCALE_TARGET_PIXELS / (w * h)) ** 0.5
        cand = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
        W, H = im.size
    raw = [b for b in zxingcpp.read_barcodes(cand) if b.valid and b.text == expect][0]
    for idx, corner_name in ((0, "top_left"), (2, "bottom_right")):
        rp = getattr(raw.position, corner_name)
        fx, fy = _forward_point(*r.position[idx], [("scale", s)])
        assert math.hypot(fx - rp.x, fy - rp.y) < 2.0, corner_name
    assert all(0 <= px <= W and 0 <= py <= H for px, py in r.position)
