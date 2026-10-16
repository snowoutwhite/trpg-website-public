"""红队（W3）：相册图片的元数据与解码攻击面。"""

from __future__ import annotations

import io
import struct

import pytest
from django.urls import reverse
from PIL import Image, PngImagePlugin
from PIL.TiffImagePlugin import IFDRational

from apps.gallery.models import Photo

from .conftest import photo_upload

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# 投毒素材
# --------------------------------------------------------------------------

# 每一个标记都对应一种「原始文件里存在、成品里绝不能存在」的字符串。
MARKERS = [
    b"SECRET-MAKE",  # EXIF Make
    b"SECRET-MODEL",  # EXIF Model（中文机型同理）
    b"SECRET-ICC-MARKER",  # ICC profile
    b"SECRET-XMP-MARKER",  # XMP 包
    b"SECRET-IPTC-VAL",  # IPTC / Photoshop 8BIM
    b"SECRET-COM-MARKER",  # JPEG COM 注释
    b"SECRET-PNG-TEXT",  # PNG tEXt
    b"SECRET-PNG-ITXT",  # PNG iTXt
    b"SECRET-ZIP-TAIL",  # 尾部附加的 ZIP
    b"SECRET-HTML-TAIL",  # 尾部附加的 HTML
]

# 容器级签名：就算内容被改写，这些结构也不该出现在成品 WebP 里。
CONTAINER_SIGNATURES = [b"Exif\x00\x00", b"xpacket", b"Photoshop 3.0", b"8BIM", b"PK\x03\x04"]

GPS_TEXT = [b"39", b"116"]  # 经纬度度数（数字串，单独 grep 噪声大，只在 EXIF 场景断言）


def _exif_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "SECRET-MAKE"
    exif[0x0110] = "SECRET-MODEL"
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (IFDRational(39), IFDRational(54), IFDRational(26))
    gps[3] = "E"
    gps[4] = (IFDRational(116), IFDRational(23), IFDRational(29))
    return exif.tobytes()


def _fake_icc() -> bytes:
    # ICC 头 4 字节是长度，后面塞标记；Pillow 原样写进 APP2 / iCCP。
    return b"\x00\x00\x02\x0cSECRET-ICC-MARKER" + b"\x00" * 500


def _insert_jpeg_segments(jpeg: bytes, segments) -> bytes:
    """在 SOI 之后插入若干 (marker, payload) 段（Pillow 不提供 IPTC/COM 写入口）。"""
    assert jpeg[:2] == b"\xff\xd8"
    out = b"\xff\xd8"
    for marker, payload in segments:
        out += bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload
    return out + jpeg[2:]


def poisoned_jpeg(size=(900, 600)) -> bytes:
    """EXIF(GPS) + ICC + XMP + IPTC + COM + 尾部 ZIP/HTML 的多态 JPEG。"""
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(
        buffer, "JPEG", exif=_exif_with_gps(), icc_profile=_fake_icc()
    )
    xmp = (
        b"http://ns.adobe.com/xap/1.0/\x00"
        b"<?xpacket begin='\xef\xbb\xbf'?><x:xmpmeta xmlns:x='adobe:ns:meta/'>"
        b"<rdf:Description SECRET-XMP-MARKER='1'/></x:xmpmeta><?xpacket end='w'?>"
    )
    iptc = (
        b"Photoshop 3.0\x00"
        b"8BIM\x04\x04\x00\x00\x00\x00\x00\x20"
        b"\x1c\x02\x05\x00\x0fSECRET-IPTC-VAL"
    )
    raw = _insert_jpeg_segments(
        buffer.getvalue(), [(0xE1, xmp), (0xED, iptc), (0xFE, b"SECRET-COM-MARKER")]
    )
    # 多态文件：合法 JPEG 之后直接接 ZIP 与 HTML，解码器读不到、grep 读得到。
    return raw + b"PK\x03\x04SECRET-ZIP-TAIL" + b"<html>SECRET-HTML-TAIL</html>"


def poisoned_png(size=(800, 500)) -> bytes:
    """tEXt + iTXt + zTXt + eXIf + iCCP + 尾部附加字节。"""
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "SECRET-PNG-TEXT")
    info.add_itxt("Description", "SECRET-PNG-ITXT")
    info.add_text("zkey", "SECRET-PNG-ZTXT", zip=True)
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(
        buffer, "PNG", pnginfo=info, exif=_exif_with_gps(), icc_profile=_fake_icc()
    )
    return buffer.getvalue() + b"PK\x03\x04SECRET-ZIP-TAIL"


def poisoned_webp(size=(700, 400)) -> bytes:
    """WebP 自己的 EXIF / XMP / ICC chunk + 尾部附加字节。"""
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 200, 90)).save(
        buffer,
        "WEBP",
        exif=_exif_with_gps(),
        xmp=b"<x:xmpmeta><?xpacket?>SECRET-XMP-MARKER</x:xmpmeta>",
        icc_profile=_fake_icc(),
    )
    return buffer.getvalue() + b"PK\x03\x04SECRET-ZIP-TAIL"


def stored_bytes(photo: Photo) -> dict[str, bytes]:
    out = {}
    for tier in ("original", "preview", "thumbnail"):
        field = getattr(photo, tier)
        with field.storage.open(field.name, "rb") as handle:
            out[tier] = handle.read()
    return out


def assert_clean(photo: Photo, *, extra: list[bytes] = ()) -> None:
    for tier, data in stored_bytes(photo).items():
        assert data[:4] == b"RIFF" and data[8:12] == b"WEBP", f"{tier} 不是 WebP"
        for marker in list(MARKERS) + CONTAINER_SIGNATURES + list(extra):
            assert marker not in data, f"{tier} 档里还留着 {marker!r}"
        # 反向验证素材确实有毒：成品干净不能是因为标记从没进去过（见下面的 sanity 用例）。


# --------------------------------------------------------------------------
# 1. 素材本身必须真的有毒（否则下面三个用例是自欺）
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("builder", "expected"),
    [
        (poisoned_jpeg, [b"SECRET-MAKE", b"SECRET-ICC-MARKER", b"SECRET-XMP-MARKER",
                         b"SECRET-IPTC-VAL", b"SECRET-COM-MARKER", b"SECRET-ZIP-TAIL",
                         b"SECRET-HTML-TAIL", b"Exif\x00\x00", b"8BIM"]),
        # PNG 的 iCCP / zTXt 是 zlib 压缩的，明文标记本来就不在字节流里 ——
        # 那种「搜不到」是不可证伪的，所以这里改断言容器块名，输出侧同样断言块名。
        (poisoned_png, [b"SECRET-PNG-TEXT", b"SECRET-PNG-ITXT", b"SECRET-MAKE",
                        b"SECRET-ZIP-TAIL", b"iCCP", b"zTXt", b"eXIf"]),
        (poisoned_webp, [b"SECRET-MAKE", b"SECRET-XMP-MARKER", b"SECRET-ICC-MARKER",
                         b"SECRET-ZIP-TAIL"]),
    ],
)
def test_source_material_really_carries_the_markers(builder, expected):
    """先证明投毒素材是有效的：不可证伪的「没搜到」不能当作剥离成功的证据。"""
    raw = builder()
    for marker in expected:
        assert marker in raw, f"素材里没写进 {marker!r}，后面的断言就没意义了"


# --------------------------------------------------------------------------
# 2. 三种容器的元数据 + 尾部附加字节，三档一律清干净
# --------------------------------------------------------------------------


def test_polyglot_jpeg_metadata_is_gone_from_all_three_tiers(finished_game, gm_factory):
    """JPEG：EXIF(GPS) / ICC / XMP / IPTC / COM / 尾部 ZIP+HTML 一个都不许带出去。"""
    game = finished_game(gm_factory())
    from apps.gallery import services

    photo = services.upload_photo(game.gm, game, photo_upload("a.jpg", poisoned_jpeg()))
    assert_clean(photo)
    for data in stored_bytes(photo).values():
        # GPS 度数字串单独查一遍：EXIF 结构没了但数字残留同样是泄露。
        for num in GPS_TEXT:
            assert num + b"/1" not in data


def test_png_text_chunks_and_exif_are_stripped(finished_game, gm_factory):
    """PNG：tEXt / iTXt / zTXt / eXIf / iCCP + 尾部附加字节。"""
    game = finished_game(gm_factory())
    from apps.gallery import services

    photo = services.upload_photo(game.gm, game, photo_upload("a.png", poisoned_png()))
    assert_clean(photo, extra=[b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"iCCP"])


def test_webp_exif_and_xmp_chunks_are_stripped(finished_game, gm_factory):
    """WebP 上传：源文件自己就是 WebP 时也必须重编码，不能原样转存。"""
    game = finished_game(gm_factory())
    from apps.gallery import services

    photo = services.upload_photo(game.gm, game, photo_upload("a.webp", poisoned_webp()))
    assert_clean(photo, extra=[b"EXIF", b"XMP "])
    # 结构层再确认一次：Pillow 读回来 info 里不该有任何元数据键。
    for tier, data in stored_bytes(photo).items():
        image = Image.open(io.BytesIO(data))
        image.load()
        assert not image.getexif(), f"{tier} 还能读出 EXIF"
        assert "icc_profile" not in image.info, f"{tier} 还带 ICC"
        assert "xmp" not in image.info, f"{tier} 还带 XMP"


def test_no_tier_is_a_byte_for_byte_copy_of_the_upload(finished_game, gm_factory):
    """连「原图」档也必须是重编码产物：任何一档等于原始字节就是元数据的后门。"""
    game = finished_game(gm_factory())
    from apps.gallery import services

    raw = poisoned_jpeg()
    photo = services.upload_photo(game.gm, game, photo_upload("a.jpg", raw))
    for tier, data in stored_bytes(photo).items():
        assert data != raw, f"{tier} 是原始字节的直接转存"


# --------------------------------------------------------------------------
# 3. 动图：只留首帧，且不炸内存
# --------------------------------------------------------------------------


def _animated(fmt: str, frames: int = 40, size=(300, 200)) -> bytes:
    images = [Image.new("RGB", size, (i * 6 % 255, 0, 0)) for i in range(frames)]
    buffer = io.BytesIO()
    images[0].save(buffer, fmt, save_all=True, append_images=images[1:], duration=40)
    return buffer.getvalue()


@pytest.mark.parametrize(("fmt", "name"), [("PNG", "a.png"), ("WEBP", "a.webp")])
def test_animated_upload_keeps_only_the_first_frame(finished_game, gm_factory, fmt, name):
    """APNG / 动态 WebP：入库后必须是单帧静图，别把整段动画连同逐帧元数据存下来。"""
    game = finished_game(gm_factory())
    from apps.gallery import services

    source = _animated(fmt)
    assert getattr(Image.open(io.BytesIO(source)), "n_frames", 1) > 1, "素材不是动图"

    photo = services.upload_photo(game.gm, game, photo_upload(name, source))
    for tier, data in stored_bytes(photo).items():
        image = Image.open(io.BytesIO(data))
        assert getattr(image, "n_frames", 1) == 1, f"{tier} 还是多帧"
        assert len(data) < len(source), f"{tier} 比动图源还大，疑似整段保留"


# --------------------------------------------------------------------------
# 4. 奇异色彩模式：要么正常入库，要么明确 4xx，绝不能 500
# --------------------------------------------------------------------------


def _mode_image(mode: str, fmt: str, **save_kwargs) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (240, 160)).save(buffer, fmt, **save_kwargs)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("label", "raw_factory", "name"),
    [
        ("CMYK JPEG", lambda: _mode_image("CMYK", "JPEG"), "a.jpg"),
        ("灰度 JPEG", lambda: _mode_image("L", "JPEG"), "a.jpg"),
        ("16 位 PNG", lambda: _mode_image("I;16", "PNG"), "a.png"),
        ("1 位 PNG", lambda: _mode_image("1", "PNG"), "a.png"),
        ("调色板 PNG", lambda: _mode_image("P", "PNG"), "a.png"),
        ("调色板+透明 PNG", lambda: _mode_image("P", "PNG", transparency=0), "a.png"),
        ("灰度+透明 PNG", lambda: _mode_image("LA", "PNG"), "a.png"),
        ("RGBA PNG", lambda: _mode_image("RGBA", "PNG"), "a.png"),
    ],
)
def test_exotic_color_modes_do_not_blow_up(
    api_client, finished_game, gm_factory, label, raw_factory, name
):
    gm = gm_factory()
    game = finished_game(gm)
    api_client.force_login(gm)
    response = api_client.post(
        reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk}),
        {"file": photo_upload(name, raw_factory())},
        format="multipart",
    )
    assert response.status_code in (201, 400), f"{label} 得到 {response.status_code}"


def test_extremely_wide_panorama_does_not_500(api_client, finished_game, gm_factory):
    """超宽全景图：体积 50 KB、像素数 1638 万（都在限额内），但单边超过 WebP 的 16383 上限。

    到不了像素闸也到不了体积闸，直接把未处理异常抛给 DRF —— 对外就是 500。
    正确姿势是要么缩到编码器能接受的范围，要么给一个明确的 4xx。
    """
    gm = gm_factory()
    game = finished_game(gm)
    api_client.force_login(gm)
    buffer = io.BytesIO()
    Image.new("RGB", (16384, 1000), (7, 7, 7)).save(buffer, "PNG")
    raw = buffer.getvalue()
    assert len(raw) < 10 * 1024 * 1024, "素材必须落在 10 MB 限额之内"
    assert 16384 * 1000 < 40_000_000, "素材必须落在像素限额之内"

    response = api_client.post(
        reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk}),
        {"file": photo_upload("panorama.png", raw)},
        format="multipart",
    )
    assert response.status_code in (201, 400), f"得到 {response.status_code}"


# --------------------------------------------------------------------------
# 5. 伪造魔数与解压炸弹（独立复验，不引用其他测试用例）
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "name", "raw"),
    [
        ("PNG 头 + SVG", "a.png", b"\x89PNG\r\n\x1a\n<svg xmlns='http://www.w3.org/2000/svg'"
                                  b"><script>alert(1)</script></svg>"),
        ("PNG 头 + HTML", "a.png", b"\x89PNG\r\n\x1a\n<html><script>alert(1)</script></html>"),
        ("JPEG 头 + HTML", "a.jpg", b"\xff\xd8\xff\xe0<html><script>alert(1)</script></html>"),
        ("纯 SVG 改名 jpg", "a.jpg", b"<svg xmlns='http://www.w3.org/2000/svg'><text>x</text></svg>"),
        ("RIFF 头 + 垃圾", "a.webp", b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32),
    ],
)
def test_forged_magic_numbers_are_refused(api_client, finished_game, gm_factory, label, name, raw):
    """魔数是「像」不是「是」：头 8 个字节对了也必须解码得出来才算图片。"""
    gm = gm_factory()
    game = finished_game(gm)
    api_client.force_login(gm)
    response = api_client.post(
        reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk}),
        {"file": photo_upload(name, raw)},
        format="multipart",
    )
    assert response.status_code == 400, f"{label} 居然被收下了"
    assert response.json()["error"]["code"] in ("invalid_image", "image_too_large")
    assert Photo.objects.count() == 0


def test_decompression_bomb_is_refused_before_decoding(api_client, finished_game, gm_factory):
    """13 万字节的纯色 PNG 声称自己有 1.44 亿像素：体积闸放行，像素闸必须拦。"""
    gm = gm_factory()
    game = finished_game(gm)
    buffer = io.BytesIO()
    Image.new("L", (12000, 12000), 0).save(buffer, "PNG")
    raw = buffer.getvalue()
    assert len(raw) < 1024 * 1024, "素材必须是「小文件大像素」才算炸弹"

    api_client.force_login(gm)
    response = api_client.post(
        reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk}),
        {"file": photo_upload("bomb.png", raw)},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "image_too_large"
    assert Photo.objects.count() == 0
