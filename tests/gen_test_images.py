"""生成测试图片：QR / Code128 / DataMatrix / EAN-13 单码图、多码图、旋转图、低质量图。

测试图使用 zxing-cpp 自带的 create_barcode 生成（无需额外系统库），
图像处理用 Pillow/numpy。期望结果写入 manifest.json 供测试断言。

跨平台说明：Pillow 在 Windows 上使用宽字符 API 读写文件，
含中文/非 ASCII 字符的路径在各平台均可正常工作。
"""
import json
from pathlib import Path

import numpy as np
import zxingcpp
from PIL import Image, ImageFilter, ImageOps

IMG_DIR = Path(__file__).resolve().parent / "images"

CASES = [
    # (文件名, 码制, 内容, 宽度, 高度)
    ("qr_hello.png", "QRCode", "https://example.com/qr-hello", 300, 300),
    ("qr_chinese.png", "QRCode", "批量条码识别测试", 300, 300),
    ("code128_a.png", "Code128", "CODE128-ABC-12345", 400, 120),
    ("code128_b.png", "Code128", "SN-20260722-0001", 400, 120),
    ("datamatrix_a.png", "DataMatrix", "DM-DATA-998877", 300, 300),
    ("ean13_a.png", "EAN13", "6901234567892", 400, 160),
]


def make_barcode(content: str, fmt: str, width: int, height: int) -> Image.Image:
    """生成条码灰度图并按整数倍放大（非整数缩放会导致条宽不均而难以解码）。"""
    b = zxingcpp.create_barcode(content, zxingcpp.barcode_format_from_str(fmt))
    img = Image.fromarray(np.array(b.to_image()))  # uint8 灰度
    w, h = img.size
    factor = max(1, min(width // w, height // h))
    return img.resize((w * factor, h * factor), Image.NEAREST)


def pad(img: Image.Image, margin: int = 30) -> Image.Image:
    return ImageOps.expand(img, margin, fill=255)


def main() -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}

    singles = {}
    for name, fmt, content, w, h in CASES:
        img = pad(make_barcode(content, fmt, w, h))
        img.save(IMG_DIR / name)
        singles[name] = (fmt, content, img)
        manifest[name] = [{"format": fmt, "content": content}]

    # 多码图：QR + Code128 + DataMatrix 竖排拼接
    parts = [np.asarray(pad(singles[n][2], 10)) for n in ("qr_hello.png", "code128_a.png", "datamatrix_a.png")]
    width = max(p.shape[1] for p in parts)
    parts = [np.pad(p, ((0, 0), (0, width - p.shape[1])), constant_values=255) for p in parts]
    multi = Image.fromarray(np.vstack(parts))
    multi.save(IMG_DIR / "multi_3codes.png")
    manifest["multi_3codes.png"] = [
        {"format": "QRCode", "content": "https://example.com/qr-hello"},
        {"format": "Code128", "content": "CODE128-ABC-12345"},
        {"format": "DataMatrix", "content": "DM-DATA-998877"},
    ]

    # 旋转 180° 的 QR 图
    rotated = Image.fromarray(np.ascontiguousarray(np.rot90(np.asarray(singles["qr_hello.png"][2]), 2)))
    rotated.save(IMG_DIR / "qr_rotated180.png")
    manifest["qr_rotated180.png"] = [
        {"format": "QRCode", "content": "https://example.com/qr-hello"},
    ]

    # 低质量图：缩小后模糊 + 噪声
    low = pad(make_barcode("LOWRES-QR-42", "QRCode", 300, 300), 10)
    low = low.resize((60, 60), Image.LANCZOS).resize((300, 300), Image.BICUBIC)
    low = low.filter(ImageFilter.GaussianBlur(1))
    arr = np.asarray(low).astype(np.float32)
    noise = np.random.default_rng(42).normal(0, 8, arr.shape)
    low = Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))
    low.save(IMG_DIR / "qr_lowres.png")
    manifest["qr_lowres.png"] = [{"format": "QRCode", "content": "LOWRES-QR-42"}]

    (IMG_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已生成 {len(manifest)} 张测试图 -> {IMG_DIR}")


# ------------------------------------------------------------ 合成疑难图（管线 v2 验证用）

def make_hard_images() -> dict:
    """生成合成疑难图，返回 {文件名: 期望内容}。

    难度调参目标：L0（zxingcpp 默认参数）打不下来，但 L1/L2 增强能救回。
    疑难类型：高斯模糊 / ±15° 旋转 / 低对比 / 线性渐变反光 / 反色 / >20MP 大图。
    """
    hard = {}

    def degrade(img, blur=0.0, noise=0.0, seed=7):
        # 每张图独立种子：噪声实现与生成顺序无关，结果可复现
        rng = np.random.default_rng(seed)
        if blur:
            img = img.filter(ImageFilter.GaussianBlur(blur))
        if noise:
            arr = np.asarray(img).astype(np.float64)
            arr = np.clip(arr + rng.normal(0, noise, arr.shape), 0, 255)
            img = Image.fromarray(arr.astype(np.uint8))
        return img

    # 1. 高斯模糊 QR：先缩小再放大破坏模块边缘 + 强模糊 + 噪声
    img = pad(make_barcode("HARD-BLUR-01", "QRCode", 300, 300), 10)
    img = img.resize((56, 56), Image.LANCZOS).resize((320, 320), Image.BICUBIC)
    img = degrade(img, blur=2.5, noise=14, seed=101)
    img.save(IMG_DIR / "hard_blur.png")
    hard["hard_blur.png"] = "HARD-BLUR-01"

    # 2. +15° 旋转一维条码 + 低对比 + 轻模糊（服务细旋转路径）
    img = pad(make_barcode("HARD-ROT15-02", "Code128", 480, 150), 20)
    img = img.rotate(-15, expand=True, fillcolor=255, resample=Image.BICUBIC)
    arr = np.asarray(img).astype(np.float64) / 255.0 * 90 + 80
    img = degrade(Image.fromarray(arr.astype(np.uint8)), blur=1.0, noise=6, seed=102)
    img.save(IMG_DIR / "hard_rot15.png")
    hard["hard_rot15.png"] = "HARD-ROT15-02"

    # 3. 低对比 QR（灰度压缩到 105..150）+ 噪声
    img = pad(make_barcode("HARD-LOWCON-03", "QRCode", 300, 300), 10)
    arr = np.asarray(img).astype(np.float64) / 255.0 * 45 + 105
    img = degrade(Image.fromarray(arr.astype(np.uint8)), noise=8, seed=103)
    img.save(IMG_DIR / "hard_lowcontrast.png")
    hard["hard_lowcontrast.png"] = "HARD-LOWCON-03"

    # 4. 线性渐变反光 QR（强渐变 + 模糊 + 噪声）
    img = pad(make_barcode("HARD-GLARE-04", "QRCode", 300, 300), 10)
    arr = np.asarray(img).astype(np.float64)
    grad = np.linspace(0, 200, arr.shape[1])[None, :]
    arr = np.clip(arr + grad, 0, 255)
    img = degrade(Image.fromarray(arr.astype(np.uint8)), blur=2.5, noise=16, seed=104)
    img.save(IMG_DIR / "hard_gradient.png")
    hard["hard_gradient.png"] = "HARD-GLARE-04"

    # 5. 反色 QR（白码黑底）+ 缩小重建 + 旋转 + 模糊 + 强噪声
    img = pad(make_barcode("HARD-INVERT-05", "QRCode", 300, 300), 10)
    img = img.resize((70, 70), Image.LANCZOS).resize((300, 300), Image.BICUBIC)
    img = ImageOps.invert(img).rotate(-12, expand=True, fillcolor=0, resample=Image.BICUBIC)
    img = degrade(img, blur=2.5, noise=25, seed=105)
    img.save(IMG_DIR / "hard_inverted.png")
    hard["hard_inverted.png"] = "HARD-INVERT-05"

    # 6. >20MP 大图（5300x3900 ≈ 20.7MP，小 QR 倾斜 + 模糊 + 噪声底）
    qr = pad(make_barcode("HARD-BIG-06", "QRCode", 115, 115), 8)
    qr = qr.rotate(-12, expand=True, fillcolor=255, resample=Image.BICUBIC)
    qr = qr.filter(ImageFilter.GaussianBlur(1.2))
    big = Image.new("L", (5300, 3900), 255)
    big.paste(qr, ((5300 - qr.size[0]) // 2, (3900 - qr.size[1]) // 2))
    arr = np.asarray(big).astype(np.float64)
    noise = np.random.default_rng(110).normal(0, 15, arr.shape)
    arr = np.clip(arr + noise, 0, 255)
    Image.fromarray(arr.astype(np.uint8)).save(IMG_DIR / "hard_big.png")
    hard["hard_big.png"] = "HARD-BIG-06"

    (IMG_DIR / "hard_manifest.json").write_text(
        json.dumps(hard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {len(hard)} 张疑难图 -> {IMG_DIR}")
    return hard


if __name__ == "__main__":
    main()
    make_hard_images()
