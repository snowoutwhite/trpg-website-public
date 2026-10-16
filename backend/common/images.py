"""图片处理工具：格式校验（魔数）、剥 EXIF、缩放、转 WebP。

相册、角色卡插图等后续 app 复用本模块，不要各自重写。
"""

from __future__ import annotations

import io
import warnings

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

from common.exceptions import ApiError

# 允许的图片格式（Pillow 的 format 名），对应 jpg / png / webp
ALLOWED_IMAGE_FORMATS = ("JPEG", "PNG", "WEBP")

# 像素总数上限（宽 × 高）。文件体积挡不住解压炸弹：一张几百字节的纯色 PNG
# 可以声称自己有上亿像素，解码时按 3~4 字节/像素吃内存。
# Pillow 自带的 MAX_IMAGE_PIXELS 只在超过 2 倍时才抛异常（且抛的是
# DecompressionBombError，不属于 OSError/ValueError，不接就会变成 500），
# 1~2 倍之间仅告警后照常解码，所以必须由我们自己定一个硬上限。
DEFAULT_MAX_PIXELS = 40_000_000  # 4000 万像素 ≈ 8000×5000，远超站内任何合理用图

# WebP 容器的硬上限：单边超过 16383 像素时 libwebp 直接拒编，Pillow 抛的是
# `ValueError: encoding error 5` —— 既不是 OSError 也不是我们的 ApiError，**不接就是 500**。
# 一张 16384×1000 的纯色 PNG 只有 50 KB、1638 万像素，体积闸与像素闸都拦不住它
# （W3 红队在 gallery 复现，W5 把修复挪到这里：任何以「不缩放」为意图调用 `to_webp`
# 的新代码都会踩同一个洞，各 app 在调用侧封顶是治标）。
WEBP_MAX_SIDE = 16383


class InvalidImage(ApiError):
    default_code = "invalid_image"
    default_detail = "这张图片无法打开，或格式不受支持。"


class ImageTooLarge(ApiError):
    default_code = "image_too_large"
    default_detail = "单张照片体积超出限制。"


def open_validated_image(
    uploaded_file,
    *,
    max_bytes: int,
    max_pixels: int | None = None,
    allowed_formats: tuple[str, ...] = ALLOWED_IMAGE_FORMATS,
) -> Image.Image:
    """校验大小、像素数与真实格式（读魔数，不信扩展名与 Content-Type），返回已加载的图像。

    `max_pixels` 不传时取 `settings.IMAGE_MAX_PIXELS`（默认 4000 万）。
    """
    if max_pixels is None:
        max_pixels = getattr(settings, "IMAGE_MAX_PIXELS", DEFAULT_MAX_PIXELS)

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > max_bytes:
        raise ImageTooLarge(f"单张照片不能超过 {max_bytes // 1024 // 1024} MB。")

    uploaded_file.seek(0)
    raw = uploaded_file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ImageTooLarge(f"单张照片不能超过 {max_bytes // 1024 // 1024} MB。")

    # 先只读文件头拿尺寸，尺寸不合格就绝不进入解码环节。
    # Pillow 的炸弹告警要升级成异常，否则 1~2 倍区间会被静默放过。
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(raw))
            width, height = probe.size
    except Image.DecompressionBombError as exc:
        raise ImageTooLarge("这张图片无法处理，可能是尺寸过大，请更换图片。") from exc
    except Image.DecompressionBombWarning as exc:
        raise ImageTooLarge("这张图片无法处理，可能是尺寸过大，请更换图片。") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImage() from exc

    if width * height > max_pixels:
        raise ImageTooLarge(f"这张图片尺寸过大（{width}×{height}），请更换尺寸较小的图片。")

    try:
        probe.verify()  # 只验结构，验完的对象不能再用
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Image.DecompressionBombError as exc:
        raise ImageTooLarge("这张图片无法处理，可能是尺寸过大，请更换图片。") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImage() from exc

    if image.format not in allowed_formats:
        raise InvalidImage()
    return image


def to_webp(
    image: Image.Image,
    *,
    max_side: int,
    quality: int = 85,
) -> bytes:
    """等比缩放到最长边不超过 max_side，剥掉 EXIF，输出 WebP 字节。

    Pillow 重新编码时不会带上原始 EXIF（除非显式传入），因此 GPS 等隐私信息自然被剥离。

    `max_side` 会被**自行封到 `WEBP_MAX_SIDE`（16383）**：调用方想「不缩放」时通常
    传一个很大的数，而 libwebp 对超宽/超高的图直接拒编、抛出的 `ValueError` 会变成 500。
    封顶只影响极端长图（16383 px 已是站内任何用图的数十倍），换来的是这个函数
    对任何输入都不会把接口打崩。
    """
    max_side = min(max_side, WEBP_MAX_SIDE)
    converted = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
    converted.thumbnail((max_side, max_side), Image.LANCZOS)
    buffer = io.BytesIO()
    converted.save(buffer, format="WEBP", quality=quality, method=4)
    return buffer.getvalue()


def webp_content_file(image: Image.Image, *, max_side: int, name: str) -> ContentFile:
    """把图像处理成 WebP 的 ContentFile，可直接赋给 ImageField。"""
    return ContentFile(to_webp(image, max_side=max_side), name=name)
