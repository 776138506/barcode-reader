"""真实难图验收：药品追溯码 5 码命中与误识防护；共识机制单元测试。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from decoder import (Attempt, DecodeResult, _consensus_results,  # noqa: E402
                     decode_image_detailed)

IMG_DIR = Path(__file__).resolve().parent / "images"
REAL = json.loads((IMG_DIR / "real_manifest.json").read_text(encoding="utf-8"))


@pytest.mark.slow
def test_real_drug_labels_max_tier():
    """真实药品追溯码图：极限档命中与误识防护（平台无关断言，D34）。

    macOS 实测 5/5；Windows/Ubuntu 上 zxing-cpp 二进制在边缘组合的
    命中略有差异，一个共识边际实例（482464 第二实例）会被降级为疑似——
    这是误识防护的正常代价（D19/D34）。断言语义：唯一码集合 ⊆ 期望、
    总数 ≥4、已知误识零泄漏。"""
    results, attempts = decode_image_detailed(IMG_DIR / "real_drug_labels.png",
                                              tier="max")
    valid = [r for r in results if not r.suspect]
    got_contents = Counter(r.content for r in valid)
    want_unique = set(REAL["expected"])
    print(f"\n真实图命中 {sum(got_contents.values())}/5: {dict(got_contents)}")
    # 有效命中必须全部属于期望集合（无误识混入）
    assert set(got_contents) <= want_unique, \
        f"出现期望外内容: {set(got_contents) - want_unique}"
    # 每种唯一码至少命中一个实例
    assert set(got_contents) == want_unique, \
        f"唯一码覆盖不全: {want_unique - set(got_contents)}"
    # 总数 ≥4（macOS 5/5；Win/Ubuntu 边际实例被共识降级时为 4/5）
    assert sum(got_contents.values()) >= 4, \
        f"命中总数 {sum(got_contents.values())} < 4: {dict(got_contents)}"
    # 已知误识不得出现在有效结果（可降级为 suspect）
    valid_set = set(got_contents)
    for misread in REAL["known_misreads"]:
        assert misread not in valid_set
    # 共识标记与坐标界内
    from PIL import Image
    with Image.open(IMG_DIR / "real_drug_labels.png") as im:
        W, H = im.size
    for r in valid:
        assert "共识" in r.strategy
        assert all(0 <= px <= W and 0 <= py <= H for px, py in r.position)


# ---------- 共识机制单元测试（合成 hits，不跑图像） ----------

def _hit(content, cx, cy, sig, layer="L3"):
    r = DecodeResult(content=content, format="Code128",
                     position=[(cx, cy), (cx + 10, cy), (cx + 10, cy + 10), (cx, cy + 10)])
    att = Attempt(layer=layer, desc=f"combo-{sig}", hit=1, ms=1.0)
    return r, att, sig


def test_consensus_single_signature_demoted():
    out = _consensus_results([_hit("A", 0, 0, "s1")], [])
    assert len(out) == 1 and out[0].suspect and "单发降级" in out[0].strategy


def test_consensus_same_signature_twice_still_demoted():
    """相邻重叠 tile 同一参数签名命中两次 ≠ 两个不同组合，仍降级。"""
    out = _consensus_results([_hit("A", 0, 0, "s1"), _hit("A", 1, 1, "s1")], [])
    assert len(out) == 1 and out[0].suspect


def test_consensus_two_signatures_valid():
    out = _consensus_results([_hit("A", 0, 0, "s1"), _hit("A", 1, 1, "s2")], [])
    assert len(out) == 1 and not out[0].suspect and "共识2" in out[0].strategy


def test_consensus_distant_same_content_separate_clusters():
    """同内容远距离（重复标签）是两个实例，各自独立判定。"""
    hits = [_hit("A", 0, 0, "s1"), _hit("A", 5, 5, "s2"),      # 实例1 共识
            _hit("A", 500, 500, "s3")]                         # 实例2 单发
    out = _consensus_results(hits, [])
    assert len(out) == 2
    valid = [r for r in out if not r.suspect]
    susp = [r for r in out if r.suspect]
    assert len(valid) == 1 and len(susp) == 1
