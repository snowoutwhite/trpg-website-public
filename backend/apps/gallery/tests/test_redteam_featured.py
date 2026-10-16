"""业务规则与安全约束。"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.db import IntegrityError, transaction

from apps.gallery.models import (
    PHOTO_PENDING_REVIEW,
    PHOTO_PUBLIC,
    PHOTO_REJECTED,
    PHOTO_TAKEN_DOWN,
    Photo,
)

pytestmark = pytest.mark.django_db

ADMIN = "/" + settings.ADMIN_URL.strip("/") + "/"


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.PROTECTED_MEDIA_ROOT = tmp_path / settings.PROTECTED_MEDIA_DIRNAME
    return tmp_path


@pytest.fixture
def photo(db, user_factory):
    """一张「已结团的团 + 已公开」的照片。"""
    from datetime import timedelta

    from django.utils import timezone

    from apps.gallery import services as gallery_services
    from apps.gallery.tests.conftest import photo_upload
    from apps.games import services as game_services
    from apps.games.models import GAME_FINISHED

    gm = user_factory(nickname="红队相册GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    started = timezone.now() - timedelta(days=1)
    game = game_services.create_game(
        gm, title="红队团", rule_system="COC", start_at=started,
        card_deadline=started, min_players=1, max_players=5,
    )
    game.status = GAME_FINISHED
    game.finished_at = timezone.now() - timedelta(hours=1)
    game.save(update_fields=["status", "finished_at"])
    return gallery_services.upload_photo(gm, game, photo_upload(), caption="合影")


@pytest.fixture
def admin_client(user_factory):
    from rest_framework.test import APIClient

    superuser = user_factory(nickname="相册后台站主", email="gallery-admin@example.com")
    superuser.is_staff = True
    superuser.is_superuser = True
    superuser.save(update_fields=["is_staff", "is_superuser"])
    client = APIClient()
    client.force_login(superuser)
    return client


# --------------------------------------------------------------------------
# 1. 约束方向一：非公开的照片不得被勾成精选
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [PHOTO_PENDING_REVIEW, PHOTO_REJECTED, PHOTO_TAKEN_DOWN])
def test_三种非公开状态都勾不上精选(photo, status):
    Photo.objects.filter(pk=photo.pk).update(status=status)
    with pytest.raises(IntegrityError), transaction.atomic():
        Photo.objects.filter(pk=photo.pk).update(is_featured=True)


@pytest.mark.parametrize("status", [PHOTO_PENDING_REVIEW, PHOTO_REJECTED, PHOTO_TAKEN_DOWN])
def test_逐条save也勾不上(photo, status):
    Photo.objects.filter(pk=photo.pk).update(status=status)
    photo.refresh_from_db()
    photo.is_featured = True
    with pytest.raises(IntegrityError), transaction.atomic():
        photo.save(update_fields=["is_featured"])


def test_bulk_update也勾不上(photo):
    from apps.gallery import services

    services.take_down_photo(photo, reason="下架")
    photo.refresh_from_db()
    photo.is_featured = True
    with pytest.raises(IntegrityError), transaction.atomic():
        Photo.objects.bulk_update([photo], ["is_featured"])


# --------------------------------------------------------------------------
# 2. 约束方向二：已精选的照片不得被悄悄推出公开状态
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [PHOTO_PENDING_REVIEW, PHOTO_REJECTED, PHOTO_TAKEN_DOWN])
def test_精选照片不得被裸update推出公开状态(photo, status):
    """这是约束真正值钱的方向：将来某条新路径改了 `status` 却忘了清 `is_featured`，
    必须当场炸在数据库上，而不是留下一张「已下架却还在首页」的照片。
    """
    from apps.homecontent import services

    services.set_photo_featured(photo, True)
    with pytest.raises(IntegrityError), transaction.atomic():
        Photo.objects.filter(pk=photo.pk).update(status=status)
    photo.refresh_from_db()
    assert photo.status == PHOTO_PUBLIC and photo.is_featured is True


def test_走service下架会同时清掉精选(photo):
    from apps.gallery import services as gallery_services
    from apps.homecontent import services

    services.set_photo_featured(photo, True)
    gallery_services.take_down_photo(photo, reason="站主下架")
    photo.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN and photo.is_featured is False


def test_下架后又恢复展示不会自动回到首页(photo, user_factory):
    """站主把一张照片从下架状态恢复成公开，它不该自动重新出现在首页上 ——
    上首页是一次**显式的**编辑动作，不是「恢复展示」的副作用。
    """
    from apps.gallery import services as gallery_services
    from apps.gallery.models import RESULT_RESTORED
    from apps.homecontent import services

    services.set_photo_featured(photo, True)
    reporter = user_factory(nickname="照片里的人")
    report = gallery_services.report_photo(reporter, photo, reason="in_photo", reason_text="我在里面")
    photo.refresh_from_db()
    if photo.status != PHOTO_TAKEN_DOWN:
        gallery_services.take_down_photo(photo, reason="站主确认下架")
        photo.refresh_from_db()
    assert photo.is_featured is False

    staff = user_factory(nickname="处理举报的站主", is_staff=True)
    report.refresh_from_db()
    if report.status != "handled":
        gallery_services.handle_report(report, by=staff, action=RESULT_RESTORED, note="误报")
    photo.refresh_from_db()
    assert photo.status == PHOTO_PUBLIC
    assert photo.is_featured is False, "恢复展示把照片自动送回了首页"


# --------------------------------------------------------------------------
# 3. Django 后台的三条批量路径
# --------------------------------------------------------------------------


def test_后台把已精选照片改成下架不得500(admin_client, photo):
    """后台详情页是能直接改 `status` 的。改成下架而没取消勾选 ——
    `PhotoAdminForm.clean()` 要给人话提示（原页 200），不能一路撞到 DB 变成 500。
    """
    from apps.homecontent import services

    services.set_photo_featured(photo, True)
    response = admin_client.post(
        f"{ADMIN}gallery/photo/{photo.pk}/change/",
        {
            "status": PHOTO_TAKEN_DOWN,
            "caption": photo.caption,
            "taken_down_reason": "站主下架",
            "is_featured": "on",
            # 举报 inline 的管理表单字段（不带会被当成缺字段）
            "reports-TOTAL_FORMS": "0",
            "reports-INITIAL_FORMS": "0",
            "reports-MIN_NUM_FORMS": "0",
            "reports-MAX_NUM_FORMS": "1000",
        },
    )
    assert response.status_code < 500, response.status_code
    photo.refresh_from_db()
    assert not (photo.is_featured and photo.status != PHOTO_PUBLIC), (
        f"后台留下了一张「{photo.status} 却仍在首页」的照片"
    )


def test_后台批量精选混合状态时逐条容错(admin_client, photo, user_factory):
    """`action_feature` 对一批照片逐条调 service。里面混一张已下架的，
    不该整批炸掉，也不该把那张已下架的推上首页。
    """
    from apps.gallery import services as gallery_services
    from apps.gallery.tests.conftest import photo_upload

    second = gallery_services.upload_photo(
        photo.uploader, photo.game, photo_upload(name="第二张.jpg"), caption="第二张"
    )
    gallery_services.take_down_photo(second, reason="先下架")

    response = admin_client.post(
        f"{ADMIN}gallery/photo/",
        {"action": "action_feature", "_selected_action": [str(photo.pk), str(second.pk)]},
        follow=True,
    )
    assert response.status_code < 500
    photo.refresh_from_db()
    second.refresh_from_db()
    assert photo.is_featured is True
    assert second.is_featured is False, "后台批量动作把一张已下架的照片推上了首页"


def test_后台批量下架会把精选一起撤掉(admin_client, photo):
    from apps.homecontent import services

    services.set_photo_featured(photo, True)
    response = admin_client.post(
        f"{ADMIN}gallery/photo/",
        {"action": "action_take_down", "_selected_action": [str(photo.pk)]},
        follow=True,
    )
    assert response.status_code < 500
    photo.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN and photo.is_featured is False


# --------------------------------------------------------------------------
# 4. 普通用户/GM 没有任何一条自己上首页的路
# --------------------------------------------------------------------------


def test_上传者没有任何接口能把自己的照片设精选(api_client, photo):
    """`is_featured` 出现在 `PhotoSerializer.fields` 里 —— 确认它是只读的，
    而且相册那边没有留下任何写路径（PATCH/PUT 都该是 405）。
    """
    api_client.force_authenticate(photo.uploader)
    for method in ("patch", "put", "post"):
        response = getattr(api_client, method)(
            f"/api/v1/gallery/photos/{photo.pk}/", {"is_featured": True}, format="json"
        )
        assert response.status_code in (401, 403, 405), f"{method} → {response.status_code}"
    photo.refresh_from_db()
    assert photo.is_featured is False


def test_上传接口的返回里精选恒为假(api_client, photo):
    from apps.gallery.tests.conftest import photo_upload

    api_client.force_authenticate(photo.uploader)
    response = api_client.post(
        f"/api/v1/gallery/games/{photo.game_id}/photos/",
        {"file": photo_upload(name="新照片.jpg"), "caption": "新的", "is_featured": True},
        format="multipart",
    )
    assert response.status_code == 201, response.content[:300]
    assert response.json()["is_featured"] is False
