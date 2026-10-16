"""对抗性测试 · 头像上传：伪造魔数、超限、图片炸弹、路径穿越文件名。"""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

pytestmark = pytest.mark.django_db

AVATAR = "/api/v1/accounts/me/avatar/"


def _png(size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (1, 2, 3)).save(buffer, format="PNG")
    return buffer.getvalue()


def _gif(size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("P", size).save(buffer, format="GIF")
    return buffer.getvalue()


def _bmp(size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size).save(buffer, format="BMP")
    return buffer.getvalue()


def _png_header_claiming(width: int, height: int) -> bytes:
    """几百字节的 PNG，但 IHDR 声称自己有 width×height 像素 —— 典型的解压炸弹。"""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b"")
    )


def _upload(name: str, data: bytes, content_type: str = "image/png"):
    return SimpleUploadedFile(name, data, content_type=content_type)


@pytest.mark.parametrize(
    "name,data,content_type,label",
    [
        ("shell.png", b"<?php system($_GET['c']); ?>", "image/png", "PHP 伪装成 PNG"),
        (
            "x.png",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            "image/png",
            "SVG 伪装成 PNG",
        ),
        ("x.png", _gif(), "image/png", "GIF 伪装成 PNG"),
        ("x.jpg", _bmp(), "image/jpeg", "BMP 伪装成 JPG"),
        ("x.png", b"", "image/png", "空文件"),
        ("x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png", "只有 PNG 魔数"),
    ],
)
def test_avatar_rejects_forged_magic_bytes(api_client, user_factory, name, data, content_type, label):
    user = user_factory(nickname="伪造上传")
    api_client.force_authenticate(user)
    response = api_client.post(
        AVATAR, {"avatar": _upload(name, data, content_type)}, format="multipart"
    )
    assert response.status_code == 400, f"{label} 被接受了"
    user.refresh_from_db()
    assert not user.avatar


def test_avatar_rejects_oversize_real_image(api_client, user_factory, settings):
    settings.AVATAR_MAX_BYTES = 2 * 1024 * 1024
    user = user_factory(nickname="超大上传")
    api_client.force_authenticate(user)
    # 随机噪声图压不动，轻松超过 2 MB
    import os

    noise = Image.frombytes("RGB", (1200, 1200), os.urandom(1200 * 1200 * 3))
    buffer = io.BytesIO()
    noise.save(buffer, format="PNG")
    payload = buffer.getvalue()
    assert len(payload) > settings.AVATAR_MAX_BYTES

    response = api_client.post(
        AVATAR, {"avatar": _upload("big.png", payload)}, format="multipart"
    )
    assert response.status_code == 400
    user.refresh_from_db()
    assert not user.avatar


def test_avatar_rejects_decompression_bomb(api_client, user_factory):
    """几百字节、却声称有数亿像素的 PNG 必须被 400 挡掉，而不是打到 500 或真去解码。"""
    user = user_factory(nickname="炸弹上传")
    api_client.force_authenticate(user)
    response = api_client.post(
        AVATAR,
        {"avatar": _upload("bomb.png", _png_header_claiming(30000, 30000))},
        format="multipart",
    )
    assert response.status_code == 400, f"图片炸弹返回了 {response.status_code}"
    user.refresh_from_db()
    assert not user.avatar


@pytest.mark.parametrize("side", [30000, 12000])
def test_open_validated_image_rejects_bomb_directly(side):
    """common.images 会被相册、战报等 app 复用，必须自己挡住炸弹，不能指望调用方先校验。

    30000² 超过 Pillow 的硬上限（抛 DecompressionBombError，不是 OSError）；
    12000² 只触发 Pillow 的告警，靠 Pillow 根本拦不住。两种都必须变成业务错误。
    """
    from common.exceptions import ApiError
    from common.images import open_validated_image

    payload = _png_header_claiming(side, side)
    with pytest.raises(ApiError) as caught:
        open_validated_image(io.BytesIO(payload), max_bytes=2 * 1024 * 1024)
    assert caught.value.get_codes() == "image_too_large", (
        f"{side}² 是被「文件坏了」顺手挡下的，不是被像素上限挡下的"
    )


def test_open_validated_image_enforces_pixel_cap_below_pillow_threshold():
    """8000² = 6400 万像素，低于 Pillow 的告警线，Pillow 完全不会吭声：
    必须由我们自己的像素上限挡住，否则一张几百 KB 的图能吃掉数百 MB 内存。"""
    from common.exceptions import ApiError
    from common.images import open_validated_image

    payload = _png_header_claiming(8000, 8000)
    assert len(payload) < 4096  # 文件本身只有几百字节
    with pytest.raises(ApiError) as caught:
        open_validated_image(io.BytesIO(payload), max_bytes=2 * 1024 * 1024)
    assert caught.value.get_codes() == "image_too_large"


def test_open_validated_image_rejects_non_allowed_format():
    from common.exceptions import ApiError
    from common.images import open_validated_image

    with pytest.raises(ApiError):
        open_validated_image(io.BytesIO(_gif()), max_bytes=1024 * 1024)


def test_avatar_filename_cannot_escape_media_root(api_client, user_factory):
    """上传文件名里的路径穿越必须完全失效（存储名由服务端生成）。"""
    user = user_factory(nickname="穿越上传")
    api_client.force_authenticate(user)
    response = api_client.post(
        AVATAR,
        {"avatar": _upload("../../../../etc/passwd.png", _png())},
        format="multipart",
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.avatar.name.startswith("avatars/")
    assert ".." not in user.avatar.name
    assert user.avatar.name.endswith(".webp")


def test_avatar_strips_exif_and_appended_payload(api_client, user_factory):
    """重编码必须把 EXIF（含 GPS）与追加在图片尾部的载荷一起丢掉。"""
    from PIL import Image as PILImage

    user = user_factory(nickname="EXIF上传")
    api_client.force_authenticate(user)

    buffer = io.BytesIO()
    image = PILImage.new("RGB", (120, 120), (9, 9, 9))
    exif = image.getexif()
    exif[0x010E] = "GPS-SECRET-MARKER"
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    payload = buffer.getvalue() + b"<?php echo 'APPENDED-MARKER'; ?>"

    response = api_client.post(
        AVATAR, {"avatar": _upload("exif.jpg", payload, "image/jpeg")}, format="multipart"
    )
    assert response.status_code == 200

    user.refresh_from_db()
    with user.avatar.open("rb") as handle:
        stored = handle.read()
    assert b"GPS-SECRET-MARKER" not in stored
    assert b"APPENDED-MARKER" not in stored


def test_guest_cannot_upload_avatar(api_client):
    response = api_client.post(AVATAR, {"avatar": _upload("a.png", _png())}, format="multipart")
    assert response.status_code in (401, 403)
