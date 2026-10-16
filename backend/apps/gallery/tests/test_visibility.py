"""可见性与受控下发：谁能看列表、谁能看单张、三档文件怎么发。"""

from __future__ import annotations

import json

import pytest
from django.urls import reverse

from apps.gallery import services
from apps.gallery.models import PHOTO_PENDING_REVIEW, PHOTO_TAKEN_DOWN
from apps.siteconfig.models import GALLERY_MODE_PRE_REVIEW

from .conftest import photo_upload

pytestmark = pytest.mark.django_db


def list_url(game) -> str:
    return reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk})


def detail_url(photo) -> str:
    return reverse("v1:gallery:photo-detail", kwargs={"pk": photo.pk})


def file_url(photo, size: str = "thumb") -> str:
    return reverse("v1:gallery:photo-file", kwargs={"pk": photo.pk}) + f"?size={size}"


# --------------------------------------------------------------------------
# 游客一律 401
# --------------------------------------------------------------------------


def test_guest_gets_401_everywhere(api_client, photo_factory):
    """相册需登录：列表 / 详情 / 文件 / 举报 全部 401。"""
    photo = photo_factory()
    assert api_client.get(list_url(photo.game)).status_code == 401
    assert api_client.get(detail_url(photo)).status_code == 401
    assert api_client.get(file_url(photo)).status_code == 401
    assert api_client.post(reverse("v1:gallery:photo-report", kwargs={"pk": photo.pk})).status_code == 401
    assert api_client.get(reverse("v1:gallery:my-reports")).status_code == 401


def test_guest_401_not_403(api_client, photo_factory):
    """必须是 401 not_authenticated，不能被 DRF 降级成 403 —— 前端要据此弹登录框。"""
    photo = photo_factory()
    response = api_client.get(file_url(photo))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


# --------------------------------------------------------------------------
# public / pending / taken_down 的三层可见性
# --------------------------------------------------------------------------


def test_logged_in_user_sees_public_photos(api_client, photo_factory, user_factory):
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    response = api_client.get(list_url(photo.game))
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["results"]] == [photo.pk]


def test_pending_photo_is_404_for_others(api_client, finished_game, gm_factory, user_factory, site_config):
    """待审照片对他人是 404（不是 403）：连存在性都不泄露。"""
    site_config.gallery_moderation_mode = GALLERY_MODE_PRE_REVIEW
    site_config.save()
    gm = gm_factory()
    game = finished_game(gm)
    photo = services.upload_photo(gm, game, photo_upload())
    assert photo.status == PHOTO_PENDING_REVIEW

    api_client.force_authenticate(user_factory())
    assert api_client.get(detail_url(photo)).status_code == 404
    assert api_client.get(file_url(photo)).status_code == 404
    assert api_client.get(list_url(game)).json()["results"] == []


def test_pending_photo_visible_to_uploader_and_owner(
    api_client, finished_game, gm_factory, owner_user, site_config
):
    site_config.gallery_moderation_mode = GALLERY_MODE_PRE_REVIEW
    site_config.save()
    gm = gm_factory()
    game = finished_game(gm)
    photo = services.upload_photo(gm, game, photo_upload())

    api_client.force_authenticate(gm)
    assert api_client.get(detail_url(photo)).status_code == 200

    api_client.force_authenticate(owner_user)
    assert api_client.get(detail_url(photo)).status_code == 200


def test_taken_down_photo_hidden_from_others(api_client, photo_factory, user_factory, owner_user):
    photo = photo_factory()
    services.take_down_photo(photo, reason="收到举报")

    api_client.force_authenticate(user_factory())
    assert api_client.get(detail_url(photo)).status_code == 404
    assert api_client.get(file_url(photo, "original")).status_code == 404

    api_client.force_authenticate(owner_user)
    assert api_client.get(detail_url(photo)).status_code == 200


def test_banned_user_cannot_see_gallery(api_client, photo_factory, user_factory):
    """封禁号看写接口被挡，看图这一路也不能更松。"""
    photo = photo_factory()
    banned = user_factory()
    banned.is_banned = True
    banned.save(update_fields=["is_banned"])
    api_client.force_authenticate(banned)
    assert api_client.get(file_url(photo)).status_code == 403


# --------------------------------------------------------------------------
# 响应体里不得出现任何存储路径
# --------------------------------------------------------------------------


def test_response_never_leaks_protected_paths(api_client, photo_factory, user_factory):
    """列表 / 详情响应体里不得出现 protected/ 路径、media 直链或 .webp 存储名。"""
    photo = photo_factory(caption="第 0 回合影")
    api_client.force_authenticate(user_factory())

    for url in (list_url(photo.game), detail_url(photo)):
        body = json.dumps(api_client.get(url).json(), ensure_ascii=False)
        assert "protected" not in body
        assert "/media/" not in body
        for field in photo.stored_files():
            assert field.name not in body
            assert field.name.split("/")[-1] not in body


def test_urls_point_at_the_controlled_endpoint(api_client, photo_factory, user_factory):
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    data = api_client.get(detail_url(photo)).json()
    base = reverse("v1:gallery:photo-file", kwargs={"pk": photo.pk})
    assert data["thumbnail_url"] == f"{base}?size=thumb"
    assert data["preview_url"] == f"{base}?size=preview"
    assert data["original_url"] == f"{base}?size=original"


# --------------------------------------------------------------------------
# 三档下发
# --------------------------------------------------------------------------


@pytest.mark.parametrize("size", ["thumb", "preview", "original"])
def test_file_endpoint_serves_webp_inline(api_client, photo_factory, user_factory, size):
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    response = api_client.get(file_url(photo, size))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Disposition"].startswith("inline;")
    body = b"".join(response.streaming_content)
    assert body[:4] == b"RIFF" and body[8:12] == b"WEBP"


def test_unknown_size_falls_back_to_thumb(api_client, photo_factory, user_factory):
    """`?size=` 传垃圾值不该 500，也不该把原图端出去。"""
    photo = photo_factory(data=None)
    api_client.force_authenticate(user_factory())
    response = api_client.get(
        reverse("v1:gallery:photo-file", kwargs={"pk": photo.pk}) + "?size=../../etc/passwd"
    )
    assert response.status_code == 200
    served = b"".join(response.streaming_content)
    with photo.thumbnail.open("rb") as handle:
        assert served == handle.read()


def test_delete_by_uploader_and_by_owner(api_client, photo_factory, user_factory, owner_user):
    photo = photo_factory()
    stored = [f.name for f in photo.stored_files()]
    storage = photo.original.storage

    # 第三方删不掉，而且拿到的是 404（不承认这张照片跟他有任何关系）
    api_client.force_authenticate(user_factory())
    assert api_client.delete(detail_url(photo)).status_code == 404

    api_client.force_authenticate(photo.uploader)
    assert api_client.delete(detail_url(photo)).status_code == 204
    for name in stored:
        assert not storage.exists(name)


def test_owner_can_delete_any_photo(api_client, photo_factory, owner_user):
    photo = photo_factory()
    api_client.force_authenticate(owner_user)
    assert api_client.delete(detail_url(photo)).status_code == 204


def test_taken_down_reason_only_for_uploader_and_owner(
    api_client, photo_factory, user_factory, owner_user
):
    """下架理由不对普通浏览者解释；但这张照片此时本来也看不见，所以用 uploader 视角测。"""
    photo = photo_factory()
    services.take_down_photo(photo, reason="当事人要求下架")
    assert photo.status == PHOTO_TAKEN_DOWN

    api_client.force_authenticate(photo.uploader)
    assert api_client.get(detail_url(photo)).json()["taken_down_reason"] == "当事人要求下架"

    api_client.force_authenticate(owner_user)
    assert api_client.get(detail_url(photo)).json()["taken_down_reason"] == "当事人要求下架"

    # 恢复公开后，第三方看得到照片但看不到理由字段的内容
    services.approve_photo(photo)
    api_client.force_authenticate(user_factory())
    assert api_client.get(detail_url(photo)).json()["taken_down_reason"] == ""
