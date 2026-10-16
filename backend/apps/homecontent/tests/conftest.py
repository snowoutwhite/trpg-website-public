"""站长内容测试的共用夹具。

造图工具复用相册那一份（`apps/gallery/tests/conftest.py` 的 `make_image_bytes`），
不在这里再抄一遍 PIL 代码。
"""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.gallery.tests.conftest import make_image_bytes  # noqa: F401  (用例直接 import 它)


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """每个用例一个干净的 MEDIA_ROOT，避免测试文件留在仓库里。"""
    settings.MEDIA_ROOT = tmp_path
    settings.PROTECTED_MEDIA_ROOT = tmp_path / settings.PROTECTED_MEDIA_DIRNAME
    return tmp_path


def image_upload(
    name: str = "规则底图.jpg",
    data: bytes | None = None,
    content_type: str = "image/jpeg",
) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data if data is not None else make_image_bytes(), content_type)


def png_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def staff_user(db, user_factory):
    """站主：`is_staff=True`，但**不是** superuser。

    用普通账号 + is_staff 来测，才能证明写接口认的是 `is_staff` 而不是超级管理员。
    """
    user = user_factory(nickname="站主", email="owner@example.com")
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.fixture
def seeded_home(db):
    """迁移预置的内容在测试库里同样存在（pytest-django 会跑全部迁移）。"""
    from apps.homecontent.models import QuickEntry, RuleSystemPreset

    return {
        "presets": list(RuleSystemPreset.objects.all()),
        "entries": list(QuickEntry.objects.all()),
    }


@pytest.fixture
def announcement_factory(db, staff_user):
    from django.utils import timezone

    from apps.homecontent.models import SiteAnnouncement

    def make(**kwargs):
        kwargs.setdefault("title", "站长公告")
        kwargs.setdefault("body", "本周六线下场地更换到二楼。")
        kwargs.setdefault("published_at", timezone.now())
        kwargs.setdefault("author", staff_user)
        return SiteAnnouncement.objects.create(**kwargs)

    return make


@pytest.fixture
def public_photo(db):
    """造一张「已结团的团 + 已公开的照片」，用于精选照片相关用例。"""
    from datetime import timedelta

    from django.utils import timezone

    from apps.gallery import services as gallery_services
    from apps.gallery.tests.conftest import photo_upload
    from apps.games import services as game_services
    from apps.games.models import GAME_FINISHED

    def make(gm=None, **kwargs):
        from apps.accounts.models import User

        if gm is None:
            gm = User.objects.create_user(
                email=f"gm{User.objects.count()}@example.com", nickname=f"照片GM{User.objects.count()}",
                password="testpass1234",
            )
            gm.is_gm = True
            gm.save(update_fields=["is_gm"])
        started = timezone.now() - timedelta(days=1)
        game = game_services.create_game(
            gm,
            title=kwargs.pop("game_title", "深潜者之夏"),
            rule_system="COC",
            start_at=started,
            card_deadline=started,
            min_players=1,
            max_players=5,
        )
        game.status = GAME_FINISHED
        game.finished_at = timezone.now() - timedelta(hours=1)
        game.save(update_fields=["status", "finished_at"])
        return gallery_services.upload_photo(gm, game, photo_upload(), caption=kwargs.pop("caption", "合影"))

    return make
