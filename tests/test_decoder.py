"""解码测试：按 manifest 断言每张图的码数、内容与码制。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decoder import decode_image, decode_images  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "images"

MANIFEST = json.loads((IMG_DIR / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(MANIFEST))
def test_decode_matches_manifest(name):
    results = decode_image(IMG_DIR / name)
    expected = MANIFEST[name]
    assert len(results) == len(expected), f"{name}: 期望 {len(expected)} 个码，实际 {len(results)}"
    got = {(r.format, r.content) for r in results}
    want = {(e["format"], e["content"]) for e in expected}
    assert got == want, f"{name}: {got} != {want}"


def test_position_points_present():
    results = decode_image(IMG_DIR / "qr_hello.png")
    assert results and len(results[0].position) == 4


def test_decode_images_batch():
    paths = [IMG_DIR / n for n in sorted(MANIFEST)]
    out = decode_images(paths)
    assert set(out) == {str(p) for p in paths}
    assert all(len(v) >= 1 for v in out.values())


def test_unreadable_image_raises():
    with pytest.raises(ValueError):
        decode_image(IMG_DIR / "manifest.json")
