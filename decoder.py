"""解码核心 v2：分层识别管线 + 图像特征提取。

对外接口 decode_image / decode_images 保持不变。

管线分层（每层命中即停）：
- L0 快速：原图 + zxingcpp 默认参数
- L1 增强（逐项尝试）：binarizer=GlobalHistogram → CLAHE 局部对比度增强
  → ±15° 细旋转（主要服务一维条码）→ 1.5x/2x 放大 → gamma 校正
- L2 极限：binarizer × 增强 × 旋转角的小组合空间，硬上限 MAX_L2_COMBOS 组
- 大图（>20MP）先等比降采样再进管线

不用 OpenCV 的原因：cv2 的 bootstrap 与 PyInstaller 冻结导入器存在结构性
冲突（见 AGENTS.md），CLAHE/gamma/旋转/缩放一律用 numpy + PIL 实现。

DecodeResult.strategy 记录命中信息："L1:clahe, 12.3ms"；未命中时
decode_image_detailed 返回的 attempts 含完整尝试信息供日志使用。
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import zxingcpp
from PIL import Image, ImageFilter, ImageOps

# 大图阈值：超过 20MP 触发降采样
MAX_PIXELS = 20_000_000
# 降采样目标：降到约 8MP——足够保住小码细节，同时限制 zxing 解码成本
DOWNSCALE_TARGET_PIXELS = 8_000_000
# L1/L2 工作图上限：增强算子（纯 numpy CLAHE 等）在大图上代价高，
# L0 之后的增强尝试一律在 ≤2MP 的工作图上进行（hit-stop，足够救回小码）
WORK_PIXELS = 2_000_000
# L2 组合空间硬上限
MAX_L2_COMBOS = 12
# L3 区域层组合硬上限：8 横带×2 放大×21 角度×2 binarizer=672 先行，
# 余量给 3×3 网格兜底；单组合为毫秒级，命中场景约 12s/张（出带即跳），
# miss 场景全扫描 worst-case 实测约 20s/张
MAX_L3_COMBOS = 750

# binarizer 短名 -> zxingcpp 枚举（profile 中以此命名）
BINARIZER_MAP = {"la": zxingcpp.Binarizer.LocalAverage,
                 "gh": zxingcpp.Binarizer.GlobalHistogram,
                 "ft": zxingcpp.Binarizer.FixedThreshold,
                 "bool": zxingcpp.Binarizer.BoolCast}


# ---------------------------------------------------------------- DecodeProfile
# 全部管线参数的结构化档案（可 JSON 序列化）。默认值 = 上方常量，
# 默认档案行为与硬编码时代完全一致（阶段 2 在线学习的地基，D20）。

# binarizer 短名 -> strategy 描述串（保持既有 strategy 格式，strategy_log 可对回）
BINARIZER_DESC = {"la": "local-average", "gh": "global-histogram",
                  "ft": "fixed-threshold", "bool": "boolcast"}


@dataclass
class PreProfile:
    max_pixels: int = MAX_PIXELS
    downscale_target: int = DOWNSCALE_TARGET_PIXELS
    work_pixels: int = WORK_PIXELS


@dataclass
class L1Profile:
    binarizers: list = field(default_factory=lambda: ["gh"])
    clahe_clip: float = 2.0
    clahe_tiles: int = 8
    sharpen: list = field(default_factory=lambda: [4, 200, 2])   # radius,percent,threshold
    angles: list = field(default_factory=lambda: [15, -15])
    upscales: list = field(default_factory=lambda: [1.5, 2.0])
    gammas: list = field(default_factory=lambda: [0.5, 2.0])


@dataclass
class L2Profile:
    binarizers: list = field(default_factory=lambda: ["la", "gh", "ft"])
    enhancers: list = field(default_factory=lambda: ["clahe", "gamma0.6"])
    angles: list = field(default_factory=lambda: [15, -15])
    max_combos: int = MAX_L2_COMBOS


@dataclass
class L3Profile:
    bands: int = 8
    band_overlap: float = 0.4
    grid: int = 3
    grid_overlap: float = 0.25
    scales: list = field(default_factory=lambda: [3, 4])
    sharpen: list = field(default_factory=lambda: [3, 150, 2])   # radius,percent,threshold
    angle_min: int = -10
    angle_max: int = 10
    band_step: int = 1
    grid_step: int = 2
    binarizers: list = field(default_factory=lambda: ["ft", "gh"])
    max_combos: int = MAX_L3_COMBOS


@dataclass
class ConsensusProfile:
    min_signatures: int = 2
    dist: int = 80


@dataclass
class DecodeProfile:
    pre: PreProfile = field(default_factory=PreProfile)
    l1: L1Profile = field(default_factory=L1Profile)
    l2: L2Profile = field(default_factory=L2Profile)
    l3: L3Profile = field(default_factory=L3Profile)
    consensus: ConsensusProfile = field(default_factory=ConsensusProfile)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "DecodeProfile":
        """从 dict 重建；缺字段回落默认（容忍旧版/手写 JSON）。"""
        d = d or {}
        def sub(key, klass):
            v = d.get(key) or {}
            fields = klass.__dataclass_fields__
            return klass(**{k: v[k] for k in v if k in fields})
        return cls(pre=sub("pre", PreProfile), l1=sub("l1", L1Profile),
                   l2=sub("l2", L2Profile), l3=sub("l3", L3Profile),
                   consensus=sub("consensus", ConsensusProfile))


DEFAULT_PROFILE = DecodeProfile()


def _l1_steps(img: Image.Image, gray: np.ndarray, base_chain: list,
              p: L1Profile):
    """L1 增强序列（命中即停，逐项尝试），每项附正向变换链。"""
    for bin_name in p.binarizers:
        yield BINARIZER_DESC[bin_name], img, {"binarizer": BINARIZER_MAP[bin_name]}, base_chain
    yield "clahe", Image.fromarray(
        _clahe(gray, clip_limit=p.clahe_clip, tiles=p.clahe_tiles)), {}, base_chain
    yield "sharpen", img.filter(ImageFilter.UnsharpMask(*p.sharpen)), {}, base_chain
    for ang in p.angles:
        rot, op = _rotate_op(img, ang)
        yield f"rotate{ang:+d}", rot, {}, base_chain + [op]
    for factor in p.upscales:
        up, op = _scale_op(img, factor)
        yield f"upscale-{factor}x", up, {}, base_chain + [op]
    for g in p.gammas:
        yield f"gamma-{g}", Image.fromarray(_gamma(gray, g)), {}, base_chain


def _l2_combos(img: Image.Image, gray: np.ndarray, base_chain: list,
               p: L2Profile):
    """L2 组合空间：binarizer × 增强 × 旋转角，硬上限 p.max_combos 组。"""
    enhancer_map = {
        "clahe": lambda: Image.fromarray(
            _clahe(gray, clip_limit=2.0, tiles=8)),
        "gamma0.6": lambda: Image.fromarray(_gamma(gray, 0.6)),
    }
    count = 0
    for rot_deg in p.angles:
        for enh_name in p.enhancers:
            base, op = _rotate_op(enhancer_map[enh_name](), rot_deg)
            for bin_name in p.binarizers:
                if count >= p.max_combos:
                    return
                count += 1
                yield (f"{bin_name}+{enh_name}+rot{rot_deg:+d}", base,
                       {"binarizer": BINARIZER_MAP[bin_name]}, base_chain + [op])


def _l3_tiles(w: int, h: int, p: L3Profile) -> list[tuple[int, int, int, int]]:
    """L3 横带粗切：p.bands 条横带（p.band_overlap 重叠）。一维码横向条带
    不被竖向切断；矩阵码由网格兜底（_l3_grid）。"""
    tiles = []
    bh = (h + p.bands - 1) // p.bands
    ov = int(bh * p.band_overlap)
    for r in range(p.bands):
        y0 = max(0, r * bh - (ov if r else 0))
        y1 = min(h, (r + 1) * bh + (ov if r < p.bands - 1 else 0))
        tiles.append((0, y0, w, y1))
    return tiles


def _l3_grid(w: int, h: int, p: L3Profile) -> list[tuple[int, int, int, int]]:
    """p.grid × p.grid 网格（p.grid_overlap 重叠），矩阵码兜底（横带全落空时才跑）。"""
    tiles = []
    g = p.grid
    tw, th = w // g, h // g
    ovx, ovy = int(tw * p.grid_overlap), int(th * p.grid_overlap)
    for r in range(g):
        for c in range(g):
            x0 = max(0, c * tw - (ovx if c else 0))
            y0 = max(0, r * th - (ovy if r else 0))
            x1 = min(w, (c + 1) * tw + (ovx if c < g - 1 else 0))
            y1 = min(h, (r + 1) * th + (ovy if r < g - 1 else 0))
            tiles.append((x0, y0, x1, y1))
    return tiles


def _l3_tile_combos(tile: Image.Image, tile_chain: list, fine_angle: bool,
                    p: L3Profile):
    """单 tile 组合：放大 p.scales → UnsharpMask(p.sharpen) → 旋转扫描
    × binarizer（p.binarizers）。fine_angle=True（横带）用 p.band_step 步进，
    否则 p.grid_step。每项产出 (desc, 候选图, kwargs, 变换链, 参数签名)。"""
    step = p.band_step if fine_angle else p.grid_step
    angles = range(p.angle_min, p.angle_max + 1, step)
    sharp_p = p.sharpen[1] if len(p.sharpen) > 1 else 150
    for scale in p.scales:
        up, sop = _scale_op(tile, scale)
        sharp = up.filter(ImageFilter.UnsharpMask(*p.sharpen))
        for ang in angles:
            if ang:
                cand, rop = _rotate_op(sharp, ang)
                chain = tile_chain + [sop, rop]
            else:
                cand, chain = sharp, tile_chain + [sop]
            for bin_name in p.binarizers:
                sig = (scale, sharp_p, ang, bin_name)
                yield (f"tile+{scale}x+sharp{sharp_p}+rot{ang:+d}+{bin_name}",
                       cand, {"binarizer": BINARIZER_MAP[bin_name]}, chain, sig)


@dataclass
class DecodeResult:
    content: str
    format: str
    position: list[tuple[int, int]] = field(default_factory=list)
    strategy: str = ""      # 命中层:参数组合, 耗时ms
    suspect: bool = False   # True = return_errors 捞回的校验失败疑似码


@dataclass
class Attempt:
    layer: str   # "PRE" / "L0" / "L1" / "L2"
    desc: str    # 参数组合描述
    hit: int     # 有效码数量（不含疑似码）
    ms: float    # 耗时毫秒


# 档位：快速=只 PRE+L0，均衡=到 L1，极限=全层
TIERS = ("fast", "balanced", "max")

# 码制白名单：显示名 -> zxingcpp 格式短名（与 BarcodeFormat.name 一致）
FORMAT_WHITELIST = {
    "QR Code": "QRCode", "Code 128": "Code128", "Code 39": "Code39",
    "EAN-13": "EAN13", "EAN-8": "EAN8", "UPC-A": "UPCA",
    "Data Matrix": "DataMatrix", "PDF417": "PDF417", "Aztec": "Aztec",
    "ITF": "ITF",
}


def formats_flag(selected: list[str] | None):
    """把选中的显示名列表转成 zxingcpp.BarcodeFormats；全选/None 返回 None（不限制）。"""
    if not selected or len(selected) >= len(FORMAT_WHITELIST):
        return None
    short = [FORMAT_WHITELIST[n] for n in selected if n in FORMAT_WHITELIST]
    if not short:
        return None
    return zxingcpp.barcode_formats_from_str(",".join(short))


# ---------------------------------------------------------------- 图像读取

def _imread_unicode(path: str | os.PathLike) -> Image.Image:
    """读取图片为 RGB PIL Image，兼容 Windows 上的非 ASCII 路径。"""
    try:
        with Image.open(path) as img:
            return img.convert("RGB")
    except Exception as exc:
        raise ValueError(f"无法读取图片: {path}") from exc


def _gray_arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"))


# ---------------------------------------------------------------- 增强算子（纯 numpy/PIL）

def _clahe(gray: np.ndarray, clip_limit: float = 2.0, tiles: int = 8) -> np.ndarray:
    """纯 numpy CLAHE：分块裁剪直方图均衡 + 块间双线性插值。

    不引 OpenCV（与 PyInstaller 冲突，见模块 docstring）。按行分块处理，
    避免大图 (h*w*256) 的插值矩阵撑爆内存。
    """
    h, w = gray.shape
    th = max(1, h // tiles)
    tw = max(1, w // tiles)
    ny = (h + th - 1) // th
    nx = (w + tw - 1) // tw

    # 每个 tile 的 灰度->灰度 映射表
    maps = np.zeros((ny, nx, 256), dtype=np.float64)
    for iy in range(ny):
        for ix in range(nx):
            tile = gray[iy * th:(iy + 1) * th, ix * tw:(ix + 1) * tw]
            hist = np.bincount(tile.ravel(), minlength=256).astype(np.float64)
            clip = clip_limit * tile.size / 256.0
            excess = np.maximum(hist - clip, 0).sum()
            hist = np.minimum(hist, clip) + excess / 256.0
            cdf = np.cumsum(hist)
            if cdf[-1] > 0:
                cdf = cdf / cdf[-1] * 255.0
            maps[iy, ix] = cdf

    # tile 中心对齐的双线性插值，按行块计算控制内存
    out = np.empty_like(gray)
    ys = (np.arange(h) + 0.5) / th - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, ny - 1)
    y1 = np.clip(y0 + 1, 0, ny - 1)
    wy = np.clip(ys - np.floor(ys), 0, 1)
    xs = (np.arange(w) + 0.5) / tw - 0.5
    x0 = np.clip(np.floor(xs).astype(int), 0, nx - 1)
    x1 = np.clip(x0 + 1, 0, nx - 1)
    wx = np.clip(xs - np.floor(xs), 0, 1)
    ROW_CHUNK = 256
    for r0 in range(0, h, ROW_CHUNK):
        r1 = min(r0 + ROW_CHUNK, h)
        m00 = maps[y0[r0:r1]][:, x0]   # (rows, w, 256)
        m01 = maps[y0[r0:r1]][:, x1]
        m10 = maps[y1[r0:r1]][:, x0]
        m11 = maps[y1[r0:r1]][:, x1]
        wxc = wx[None, :, None]
        top = m00 * (1 - wxc) + m01 * wxc
        bot = m10 * (1 - wxc) + m11 * wxc
        wyc = wy[r0:r1, None, None]
        m = top * (1 - wyc) + bot * wyc
        v = gray[r0:r1].astype(int)[..., None]
        out[r0:r1] = np.take_along_axis(m, v, axis=2)[..., 0].astype(np.uint8)
    return out


def _gamma(gray: np.ndarray, gamma: float) -> np.ndarray:
    lut = ((np.arange(256) / 255.0) ** gamma * 255.0).astype(np.uint8)
    return lut[gray]


def _rotate_op(img: Image.Image, degrees: float):
    """细旋转（PIL 角度为逆时针正方向），白底扩展画布。

    返回 (旋转后图, 变换算子)。算子记录 PIL 角度、旋转前后尺寸，
    供命中后把码位置反变换回原图坐标系。
    """
    fill = (255, 255, 255) if img.mode == "RGB" else 255
    rot = img.rotate(-degrees, expand=True, fillcolor=fill,
                     resample=Image.BICUBIC)
    return rot, ("rot", degrees, img.size, rot.size)


def _scale_op(img: Image.Image, factor: float):
    """缩放，返回 (缩放后图, ("scale", factor))。"""
    w, h = img.size
    new = img.resize((max(1, int(w * factor)), max(1, int(h * factor))),
                     Image.BICUBIC if factor >= 1 else Image.LANCZOS)
    return new, ("scale", factor)


def _invert_point(x: float, y: float, ops: list) -> tuple[float, float]:
    """把候选图坐标反变换回原图坐标系。

    ops 为正向（原图→候选图）变换链，此处逆序逆变换：
    - scale：除以倍率
    - offset：tile 裁剪，候选坐标 + tile 原点
    - rot：以图中心（size/2）为原点旋转 -θ，θ=radians(degrees)。
      已对 PIL rotate(expand=True) 实证，任意角误差 <0.2px。
    """
    for op in reversed(ops):
        kind = op[0]
        if kind == "scale":
            x /= op[1]
            y /= op[1]
        elif kind == "offset":
            x += op[1]
            y += op[2]
        else:
            _, degrees, (wo, ho), (wn, hn) = op
            th = math.radians(degrees)
            dx, dy = x - wn / 2, y - hn / 2
            x = math.cos(th) * dx + math.sin(th) * dy + wo / 2
            y = -math.sin(th) * dx + math.cos(th) * dy + ho / 2
    return x, y


def _forward_point(x: float, y: float, ops: list) -> tuple[float, float]:
    """正向（原图→候选图）变换，_invert_point 的逆运算（测试复核用）。"""
    for op in ops:
        kind = op[0]
        if kind == "scale":
            x *= op[1]
            y *= op[1]
        elif kind == "offset":
            x -= op[1]
            y -= op[2]
        else:
            _, degrees, (wo, ho), (wn, hn) = op
            th = math.radians(degrees)
            dx, dy = x - wo / 2, y - ho / 2
            x = math.cos(th) * dx - math.sin(th) * dy + wn / 2
            y = math.sin(th) * dx + math.cos(th) * dy + hn / 2
    return x, y


# ---------------------------------------------------------------- 解码执行

def _to_results(barcodes, chain: list | None = None,
                include_suspect: bool = False) -> tuple[list[DecodeResult], list[DecodeResult]]:
    """拆分为 (有效结果, 疑似结果)。疑似 = return_errors 捞回且文本非空的
    校验失败码（空文本的噪声错误结果丢弃）。位置已按 chain 反变换。"""
    results: list[DecodeResult] = []
    suspects: list[DecodeResult] = []
    for b in barcodes:
        if b.valid:
            target = results
        elif include_suspect and b.text:
            target = suspects
        else:
            continue
        pts = []
        pos = b.position
        for corner in (pos.top_left, pos.top_right, pos.bottom_right, pos.bottom_left):
            x, y = float(corner.x), float(corner.y)
            if chain:
                x, y = _invert_point(x, y, chain)
            pts.append((int(round(x)), int(round(y))))
        target.append(DecodeResult(content=b.text, format=b.format.name,
                                   position=pts, suspect=not b.valid))
    return results, suspects


def _try(img, layer: str, desc: str, chain: list | None = None,
         include_suspect: bool = False,
         **kwargs) -> tuple[list[DecodeResult], list[DecodeResult], Attempt]:
    t0 = time.perf_counter()
    found = zxingcpp.read_barcodes(img, return_errors=include_suspect, **kwargs)
    ms = (time.perf_counter() - t0) * 1000
    results, suspects = _to_results(found, chain, include_suspect)
    return results, suspects, Attempt(layer=layer, desc=desc,
                                      hit=len(results), ms=round(ms, 1))


def decode_image_detailed(path: str | os.PathLike, tier: str = "balanced",
                          formats=None, include_suspect: bool = True,
                          profile: DecodeProfile | None = None,
                          ) -> tuple[list[DecodeResult], list[Attempt]]:
    """识别图片中的所有码，返回 (结果列表, 全部尝试记录)。

    - tier: "fast"（只 PRE+L0）/ "balanced"（到 L1）/ "max"（全层）
    - formats: zxingcpp.BarcodeFormats 或 None（不限制码制）
    - include_suspect: 每层带 return_errors，校验失败的疑似码一并返回
      （suspect=True；命中层的疑似码随结果返回，全程未命中时取 L0 层疑似码）
    每层命中后 position 已按变换链反变换回原图坐标系。
    """
    if tier not in TIERS:
        raise ValueError(f"未知档位: {tier}")
    profile = profile or DEFAULT_PROFILE
    img = _imread_unicode(path)
    attempts: list[Attempt] = []
    chain: list = []  # 正向（原图→当前图）变换链
    extra = {"formats": formats} if formats is not None else {}

    # 大图先等比降采样再进管线（>20MP 触发，降到约 8MP）
    w, h = img.size
    if w * h > profile.pre.max_pixels:
        t0 = time.perf_counter()
        scale = (profile.pre.downscale_target / (w * h)) ** 0.5
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)
        chain = chain + [("scale", scale)]
        attempts.append(Attempt(
            layer="PRE", desc=f"downscale-{scale:.2f}x({w}x{h}->{img.size[0]}x{img.size[1]})",
            hit=0, ms=round((time.perf_counter() - t0) * 1000, 1)))

    # L0 快速：原图（或 PRE 降采样后的图）+ 默认参数
    results, l0_suspects, att = _try(img, "L0", "default", chain,
                                     include_suspect, **extra)
    attempts.append(att)
    if results:
        for r in l0_suspects:
            r.strategy = results[0].strategy if results else ""
        return _with_strategy(results + l0_suspects, att), attempts
    if tier == "fast":
        for r in l0_suspects:
            r.strategy = "L0:default（未命中）"
        return l0_suspects, attempts

    # L1/L2 在 ≤2MP 的工作图上进行，控制纯 numpy 增强算子的成本
    work = img
    work_chain = chain
    w, h = work.size
    if w * h > profile.pre.work_pixels:
        t0 = time.perf_counter()
        scale = (profile.pre.work_pixels / (w * h)) ** 0.5
        work = work.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                           Image.LANCZOS)
        work_chain = work_chain + [("scale", scale)]
        attempts.append(Attempt(
            layer="PRE", desc=f"workdownscale-{scale:.2f}x", hit=0,
            ms=round((time.perf_counter() - t0) * 1000, 1)))
    gray = _gray_arr(work)

    # L1 增强：逐项尝试，命中即停
    for desc, candidate, kwargs, cand_chain in _l1_steps(work, gray, work_chain, profile.l1):
        results, suspects, att = _try(candidate, "L1", desc, cand_chain,
                                      include_suspect, **{**kwargs, **extra})
        attempts.append(att)
        if results:
            return _with_strategy(results + suspects, att), attempts

    if tier == "balanced":
        for r in l0_suspects:
            r.strategy = "L0:default（未命中）"
        return l0_suspects, attempts

    # L2/L3 激进层（仅极限档）：不命中即停，收集全部有效命中后按
    # （内容 + 原图位置）聚类、按参数签名做共识判定，防激进变换产出假码
    hits: list[tuple[DecodeResult, Attempt, object]] = []  # (结果, 尝试, 签名)
    for desc, candidate, kwargs, cand_chain in _l2_combos(work, gray, work_chain, profile.l2):
        results, _suspects, att = _try(candidate, "L2", desc, cand_chain,
                                       include_suspect, **{**kwargs, **extra})
        attempts.append(att)
        for r in results:
            hits.append((r, att, desc))

    # L3 横带扫描：同带内某内容集齐 ≥2 个签名即跳到下一带；
    # 横带全落空才跑 3×3 网格兜底（矩阵码）
    l3_count = 0
    l3_hit_before = len(hits)
    for tiles, fine in ((_l3_tiles(*work.size, profile.l3), True),):
        for (x0, y0, x1, y1) in tiles:
            tile = work.crop((x0, y0, x1, y1))
            tile_chain = work_chain + [("offset", x0, y0)]
            tile_sigs: dict[str, set] = {}
            for desc, cand, kwargs, chain, sig in _l3_tile_combos(tile, tile_chain, fine, profile.l3):
                if l3_count >= profile.l3.max_combos:
                    break
                l3_count += 1
                results, _suspects, att = _try(cand, "L3", desc, chain,
                                               include_suspect, **{**kwargs, **extra})
                attempts.append(att)
                for r in results:
                    hits.append((r, att, sig))
                    tile_sigs.setdefault(r.content, set()).add(sig)
                if any(len(s) >= profile.consensus.min_signatures for s in tile_sigs.values()):
                    break  # 本带已有内容达成签名共识，提前结束本带
    if len(hits) == l3_hit_before:  # 横带零命中 → 网格兜底
        for (x0, y0, x1, y1) in _l3_grid(*work.size, profile.l3):
            tile = work.crop((x0, y0, x1, y1))
            tile_chain = work_chain + [("offset", x0, y0)]
            for desc, cand, kwargs, chain, sig in _l3_tile_combos(tile, tile_chain, False, profile.l3):
                if l3_count >= profile.l3.max_combos:
                    break
                l3_count += 1
                results, _suspects, att = _try(cand, "L3", desc, chain,
                                               include_suspect, **{**kwargs, **extra})
                attempts.append(att)
                for r in results:
                    hits.append((r, att, sig))

    return _consensus_results(hits, l0_suspects, profile.consensus), attempts


# 误识防护：同一（内容+位置）聚类需 ≥2 个不同参数组合命中才算有效
CONSENSUS_MIN = 2
# 聚类中心距阈值（原图坐标系 px）：同内容同位置的不同实例（如重复标签）
# 间距大于此值视为不同聚类
CONSENSUS_DIST = 80


def _result_center(r: DecodeResult) -> tuple[float, float]:
    if not r.position:
        return (0.0, 0.0)
    xs = [p[0] for p in r.position]
    ys = [p[1] for p in r.position]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _consensus_results(hits: list[tuple[DecodeResult, Attempt, object]],
                       l0_suspects: list[DecodeResult],
                       consensus: ConsensusProfile | None = None) -> list[DecodeResult]:
    """L2/L3 命中的共识判定：同一（内容+位置）聚类需 ≥min_signatures 个
    不同参数签名（放大/锐化/角度/binarizer，tile 差异不算）才算有效；
    单签名命中降级为 suspect（走疑似码语义，不入历史库）。"""
    cons = consensus or ConsensusProfile()
    clusters: list[list] = []  # [content, center, [(result, attempt, sig), ...]]
    for r, att, sig in hits:
        center = _result_center(r)
        for cl in clusters:
            if (cl[0] == r.content
                    and math.hypot(cl[1][0] - center[0], cl[1][1] - center[1])
                    <= cons.dist):
                cl[2].append((r, att, sig))
                break
        else:
            clusters.append([r.content, center, [(r, att, sig)]])

    valid: list[DecodeResult] = []
    demoted: list[DecodeResult] = []
    for _content, _center, members in clusters:
        first_r, first_att, _sig = members[0]
        sigs = {m[2] for m in members}
        if len(sigs) >= cons.min_signatures:
            first_r.suspect = False
            first_r.strategy = f"{first_att.layer}:{first_att.desc}（共识{len(sigs)}）, {first_att.ms:.1f}ms"
            valid.append(first_r)
        else:
            first_r.suspect = True
            first_r.strategy = f"{first_att.layer}:{first_att.desc}（单发降级）, {first_att.ms:.1f}ms"
            demoted.append(first_r)
    return valid + demoted + l0_suspects


def _with_strategy(results: list[DecodeResult], att: Attempt) -> list[DecodeResult]:
    strategy = f"{att.layer}:{att.desc}, {att.ms:.1f}ms"
    for r in results:
        r.strategy = strategy
    return results


def decode_image(path: str | os.PathLike, tier: str = "balanced",
                 formats=None, include_suspect: bool = True,
                 profile: DecodeProfile | None = None) -> list[DecodeResult]:
    """识别图片中的所有条码/二维码（对外接口不变，新增可选控制项）。"""
    return decode_image_detailed(path, tier, formats, include_suspect, profile)[0]


def decode_images(paths: list[str | os.PathLike]) -> dict[str, list[DecodeResult]]:
    """批量识别，返回 {路径字符串: [DecodeResult, ...]}。"""
    return {str(p): decode_image(p) for p in paths}


# ---------------------------------------------------------------- 图像特征提取

def extract_features(img: Image.Image) -> dict:
    """提取图像特征（纯 numpy/PIL）：亮度/对比度/模糊度/尺寸/宽高比/估计主旋转角。

    主旋转角为梯度方向直方图主峰（模 90° 映射到 (-45, 45]），是启发式估计，
    主要对一维条码/纹理明显的图有效。
    """
    gray = img.convert("L")
    gray.thumbnail((512, 512))  # 缩样加速，特征对分辨率不敏感
    arr = np.asarray(gray).astype(np.float64)
    gy, gx = np.gradient(arr)
    mag2 = gx * gx + gy * gy
    weight = np.sqrt(mag2)
    mask = weight > weight.mean() if weight.size else weight > 0
    if mask.any():
        angles = np.degrees(np.arctan2(gy, gx))[mask] % 180.0
        hist, _ = np.histogram(angles, bins=180, range=(0, 180), weights=weight[mask])
        peak = float(hist.argmax())
        rotation_est = ((peak + 45.0) % 90.0) - 45.0
    else:
        rotation_est = 0.0
    w, h = img.size
    return {
        "brightness": round(float(arr.mean()), 2),
        "contrast": round(float(arr.std()), 2),
        "blur": round(float(mag2.var()), 2),
        "width": w,
        "height": h,
        "aspect": round(w / h, 4) if h else 0.0,
        "rotation_est": round(rotation_est, 1),
    }


def extract_features_from_path(path: str | os.PathLike) -> dict:
    with Image.open(path) as img:
        return extract_features(img.convert("RGB"))


def attempts_to_dicts(attempts: list[Attempt]) -> list[dict]:
    return [asdict(a) for a in attempts]
