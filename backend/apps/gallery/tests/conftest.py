"""相册测试的共用夹具。

造图工具全部在这里，测试里不要各写一份 PIL 代码。
"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from PIL.TiffImagePlugin import IFDRational


def make_image_bytes(
    *,
    size: tuple[int, int] = (1200, 800),
    fmt: str = "JPEG",
    color: tuple[int, int, int] = (180, 40, 40),
    exif: Image.Exif | None = None,
) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    kwargs = {}
    if exif is not None:
        kwargs["exif"] = exif
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def exif_with_gps(orientation: int | None = None) -> Image.Exif:
    """构造一份带 GPS（含经纬度）与相机型号的 EXIF，可选带 orientation。"""
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"  # Make
    exif[0x0110] = "拍摄者的手机"  # Model
    if orientation is not None:
        exif[0x0112] = orientation
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (IFDRational(39), IFDRational(54), IFDRational(26))
    gps[3] = "E"
    gps[4] = (IFDRational(116), IFDRational(23), IFDRational(29))
    return exif


def photo_upload(
    name: str = "活动照.jpg",
    data: bytes | None = None,
    content_type: str = "image/jpeg",
) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data if data is not None else make_image_bytes(), content_type)


def read_exif(raw: bytes) -> dict:
    """把字节读回来，返回 EXIF 字典（含展开的 GPS IFD）。"""
    image = Image.open(io.BytesIO(raw))
    image.load()
    exif = image.getexif()
    merged = dict(exif)
    try:
        merged.update({f"gps:{k}": v for k, v in exif.get_ifd(0x8825).items()})
    except Exception:  # pragma: no cover
        pass
    return merged


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """每个用例一个干净的 MEDIA_ROOT，避免测试文件留在仓库里。"""
    settings.MEDIA_ROOT = tmp_path
    settings.PROTECTED_MEDIA_ROOT = tmp_path / settings.PROTECTED_MEDIA_DIRNAME
    return tmp_path


@pytest.fixture
def gm_factory(db, user_factory):
    def make(**kwargs):
        user = user_factory(**kwargs)
        user.is_gm = True
        user.save(update_fields=["is_gm"])
        return user

    return make


@pytest.fixture
def owner_user(db, user_factory):
    """站主：持有 `gallery.moderate_photo` 权限位。"""
    from django.contrib.auth.models import Permission

    user = user_factory(nickname="站主")
    user.user_permissions.add(Permission.objects.get(codename="moderate_photo"))
    return type(user).objects.get(pk=user.pk)  # 刷新权限缓存


@pytest.fixture
def finished_game(db, gm_factory):
    """造一个「刚刚结团」的团，相册上传窗口正开着。"""
    from apps.games import services as game_services
    from apps.games.models import GAME_FINISHED

    def make(gm=None, *, finished_ago: timedelta | None = None, **kwargs):
        gm = gm or gm_factory()
        kwargs.setdefault("title", "深潜者之夏")
        kwargs.setdefault("rule_system", "COC")
        started = timezone.now() - timedelta(days=1)
        kwargs.setdefault("start_at", started)
        kwargs.setdefault("card_deadline", started)
        kwargs.setdefault("min_players", 1)
        kwargs.setdefault("max_players", 5)
        game = game_services.create_game(gm, **kwargs)
        game.status = GAME_FINISHED
        game.finished_at = timezone.now() - (finished_ago or timedelta(hours=1))
        game.save(update_fields=["status", "finished_at"])
        return game

    return make


@pytest.fixture
def photo_factory(db, finished_game):
    """直接经 service 造一张照片（走真实的上传链路，包含 EXIF 剥离与三档生成）。"""
    from apps.gallery import services

    def make(game=None, gm=None, *, caption: str = "", data: bytes | None = None, **kwargs):
        game = game or finished_game(gm)
        return services.upload_photo(
            game.gm, game, photo_upload(data=data), caption=caption, **kwargs
        )

    return make
