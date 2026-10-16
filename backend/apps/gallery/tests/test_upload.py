"""上传链路：权限、窗口、配额、体积、魔数、EXIF、orientation。"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from django.urls import reverse
from PIL import Image

from apps.gallery import services
from apps.gallery.models import (
    PHOTO_MAX_BYTES,
    PHOTO_MAX_PER_GAME,
    PHOTO_PENDING_REVIEW,
    PHOTO_PUBLIC,
    Photo,
)
from apps.games.models import GAME_RECRUITING
from apps.siteconfig.models import (
    GALLERY_MODE_POST_REPORT,
    GALLERY_MODE_PRE_REVIEW,
    GALLERY_MODE_PUBLIC,
)

from .conftest import exif_with_gps, make_image_bytes, photo_upload, read_exif

pytestmark = pytest.mark.django_db


def upload_url(game) -> str:
    return reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk})


def post_photo(api_client, user, game, **kwargs):
    api_client.force_authenticate(user)
    payload = {"file": kwargs.pop("file", photo_upload()), **kwargs}
    return api_client.post(upload_url(game), payload, format="multipart")


# --------------------------------------------------------------------------
# 权限与窗口
# --------------------------------------------------------------------------


def test_non_gm_cannot_upload(api_client, finished_game, user_factory):
    """非本团 GM 上传 → 403 photo_not_game_gm。"""
    game = finished_game()
    response = post_photo(api_client, user_factory(), game)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "photo_not_game_gm"
    assert Photo.objects.count() == 0


def test_other_gm_cannot_upload_to_someone_elses_game(api_client, finished_game, gm_factory):
    """别的团的 GM 也不行 —— 「是 GM」不等于「是此团的 GM」。"""
    game = finished_game()
    response = post_photo(api_client, gm_factory(), game)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "photo_not_game_gm"


def test_guest_upload_is_401(api_client, finished_game):
    game = finished_game()
    response = api_client.post(upload_url(game), {"file": photo_upload()}, format="multipart")
    assert response.status_code == 401


def test_cannot_upload_before_game_finished(api_client, finished_game, gm_factory):
    """团没结团就传图 → 400 photo_game_not_finished（需求 5：结团才解锁传图）。"""
    gm = gm_factory()
    game = finished_game(gm)
    game.status = GAME_RECRUITING
    game.finished_at = None
    game.save(update_fields=["status", "finished_at"])

    response = post_photo(api_client, gm, game)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "photo_game_not_finished"


def test_upload_outside_window_rejected(api_client, finished_game, gm_factory, site_config):
    """结团超过 gallery_upload_window_days（默认 30 天）就传不了了。"""
    gm = gm_factory()
    game = finished_game(gm, finished_ago=timedelta(days=31))
    response = post_photo(api_client, gm, game)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "gallery_window_closed"


def test_window_boundary_is_configurable(api_client, finished_game, gm_factory, site_config):
    """窗口天数读站点配置，不硬编码 30。"""
    site_config.gallery_upload_window_days = 40
    site_config.save()
    gm = gm_factory()
    game = finished_game(gm, finished_ago=timedelta(days=31))
    assert post_photo(api_client, gm, game).status_code == 201


def test_quota_50_photos_per_game(api_client, finished_game, gm_factory):
    """每团 50 张：第 51 张被拒。"""
    gm = gm_factory()
    game = finished_game(gm)
    tiny = make_image_bytes(size=(4, 4))
    for _ in range(PHOTO_MAX_PER_GAME):
        services.upload_photo(gm, game, photo_upload(data=tiny))
    assert Photo.objects.filter(game=game).count() == PHOTO_MAX_PER_GAME

    response = post_photo(api_client, gm, game, file=photo_upload(data=tiny))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "gallery_quota_exceeded"


# --------------------------------------------------------------------------
# 输入校验
# --------------------------------------------------------------------------


def test_exactly_max_bytes_is_accepted_and_one_more_is_not(api_client, finished_game, gm_factory):
    """10 MB 边界：正好 10 MB 收，10 MB + 1 拒。"""
    gm = gm_factory()
    game = finished_game(gm)

    # 用不可压缩的噪声把 PNG 撑到指定大小很麻烦，这里直接在合法 JPEG 后面补零字节：
    # JPEG 解码器遇到 EOI 之后的垃圾会忽略，所以图仍然合法，但 size 是我们要的。
    base = make_image_bytes(size=(64, 64))
    at_limit = base + b"\x00" * (PHOTO_MAX_BYTES - len(base))
    over_limit = at_limit + b"\x00"
    assert len(at_limit) == PHOTO_MAX_BYTES

    assert post_photo(api_client, gm, game, file=photo_upload(data=at_limit)).status_code == 201

    response = post_photo(api_client, gm, game, file=photo_upload(data=over_limit))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "image_too_large"


def test_forged_magic_number_rejected(api_client, finished_game, gm_factory):
    """扩展名是 .jpg、内容不是图片 → invalid_image。魔数说了算。"""
    gm = gm_factory()
    game = finished_game(gm)
    payload = b"GIF89a" + b"\x00" * 128  # 真 GIF 头也不在白名单里
    response = post_photo(api_client, gm, game, file=photo_upload("伪装.jpg", payload))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_image"
    assert Photo.objects.count() == 0


def test_real_gif_renamed_to_jpg_rejected(api_client, finished_game, gm_factory):
    """把真 GIF 改名成 .jpg：扩展名过了，魔数这关过不了。"""
    gm = gm_factory()
    game = finished_game(gm)
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="GIF")
    response = post_photo(api_client, gm, game, file=photo_upload("gif伪装.jpg", buffer.getvalue()))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_image"


def test_bad_extension_rejected_even_with_valid_jpeg_bytes(api_client, finished_game, gm_factory):
    """内容是合法 JPEG，但扩展名不在 jpg/png/webp 里 → 照样拒（扩展名 + 魔数双校验）。"""
    gm = gm_factory()
    game = finished_game(gm)
    response = post_photo(api_client, gm, game, file=photo_upload("照片.bmp", make_image_bytes()))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_image"


def test_decompression_bomb_rejected(api_client, finished_game, gm_factory, settings):
    """几十字节的纯色 PNG 声称自己上亿像素 → image_too_large，不能把进程 OOM 掉。"""
    gm = gm_factory()
    game = finished_game(gm)
    settings.IMAGE_MAX_PIXELS = 1_000_000
    payload = make_image_bytes(size=(2000, 2000), fmt="PNG")
    response = post_photo(api_client, gm, game, file=photo_upload("炸弹.png", payload))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "image_too_large"


def test_path_traversal_filename_never_reaches_storage(finished_game, gm_factory):
    """带路径穿越的文件名一个字符都不进存储路径。"""
    gm = gm_factory()
    game = finished_game(gm)
    evil = photo_upload("../../../../etc/passwd.jpg")
    photo = services.upload_photo(gm, game, evil)
    for field in photo.stored_files():
        assert field.name.startswith("protected/gallery/")
        assert ".." not in field.name
        assert "passwd" not in field.name
        assert field.name.endswith(".webp")


# --------------------------------------------------------------------------
# EXIF 与 orientation（红线：真人照片必须剥 GPS）
# --------------------------------------------------------------------------


def test_exif_and_gps_are_stripped_from_all_three_tiers(finished_game, gm_factory):
    """构造带 GPS EXIF 的 JPEG，上传后三档文件里都读不到任何 EXIF。"""
    gm = gm_factory()
    game = finished_game(gm)
    raw = make_image_bytes(size=(800, 600), exif=exif_with_gps())

    # 前置断言：源文件确实带着 GPS，否则这个用例证明不了任何事。
    source_exif = read_exif(raw)
    assert source_exif, "构造的源图没有 EXIF，用例本身失效"
    assert any(str(k).startswith("gps:") for k in source_exif), "源图缺 GPS，用例本身失效"

    photo = services.upload_photo(gm, game, photo_upload(data=raw))
    for field in photo.stored_files():
        with field.open("rb") as handle:
            stored = handle.read()
        assert read_exif(stored) == {}, f"{field.name} 里还残留 EXIF"
        assert b"SecretCamera" not in stored
        assert b"Exif" not in stored[:64]


def test_exif_orientation_applied_before_stripping(finished_game, gm_factory):
    """orientation=6（顺时针 90°）的横图，落盘后应变成竖图。

    先转向再剥 —— 顺序反了就是「剥干净了但照片是歪的」。
    """
    gm = gm_factory()
    game = finished_game(gm)
    raw = make_image_bytes(size=(400, 200), exif=exif_with_gps(orientation=6))

    photo = services.upload_photo(gm, game, photo_upload(data=raw))
    assert (photo.width, photo.height) == (200, 400)

    with photo.original.open("rb") as handle:
        image = Image.open(io.BytesIO(handle.read()))
    assert image.size == (200, 400)
    assert read_exif(raw) != {}  # 源图确实带 orientation


def test_three_tiers_have_expected_sizes(finished_game, gm_factory):
    """缩略 400 / 预览 1600 / 原图不缩放，全部 WebP。"""
    gm = gm_factory()
    game = finished_game(gm)
    photo = services.upload_photo(
        gm, game, photo_upload(data=make_image_bytes(size=(3000, 1500)))
    )

    def dimensions(field):
        with field.open("rb") as handle:
            image = Image.open(io.BytesIO(handle.read()))
            image.load()
            return image.size, image.format

    assert dimensions(photo.original) == ((3000, 1500), "WEBP")
    assert dimensions(photo.preview) == ((1600, 800), "WEBP")
    assert dimensions(photo.thumbnail) == ((400, 200), "WEBP")
    assert (photo.width, photo.height) == (3000, 1500)


def test_small_image_is_not_upscaled(finished_game, gm_factory):
    """比缩略档还小的图不放大。"""
    gm = gm_factory()
    game = finished_game(gm)
    photo = services.upload_photo(gm, game, photo_upload(data=make_image_bytes(size=(120, 90))))
    with photo.thumbnail.open("rb") as handle:
        assert Image.open(io.BytesIO(handle.read())).size == (120, 90)


# --------------------------------------------------------------------------
# 三种审核模式的初始状态
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (GALLERY_MODE_PUBLIC, PHOTO_PUBLIC),
        (GALLERY_MODE_PRE_REVIEW, PHOTO_PENDING_REVIEW),
        (GALLERY_MODE_POST_REPORT, PHOTO_PUBLIC),
    ],
)
def test_initial_status_follows_site_mode(finished_game, gm_factory, site_config, mode, expected):
    site_config.gallery_moderation_mode = mode
    site_config.save()
    gm = gm_factory()
    game = finished_game(gm)
    photo = services.upload_photo(gm, game, photo_upload())
    assert photo.status == expected


def test_mode_switch_does_not_retroactively_change_existing_photos(
    finished_game, gm_factory, site_config
):
    """切换模式不回溯已有照片状态（任务口径）。"""
    site_config.gallery_moderation_mode = GALLERY_MODE_PUBLIC
    site_config.save()
    gm = gm_factory()
    game = finished_game(gm)
    old = services.upload_photo(gm, game, photo_upload())
    assert old.status == PHOTO_PUBLIC

    site_config.gallery_moderation_mode = GALLERY_MODE_PRE_REVIEW
    site_config.save()
    new = services.upload_photo(gm, game, photo_upload())

    old.refresh_from_db()
    assert old.status == PHOTO_PUBLIC
    assert new.status == PHOTO_PENDING_REVIEW
