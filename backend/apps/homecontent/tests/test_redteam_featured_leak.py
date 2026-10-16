"""业务规则与安全约束。"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def featured(public_photo, site_config):
    """一张已精选、站级开关开着、可见范围 public 的照片。"""
    from apps.homecontent import services

    photo = public_photo()
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True
    site_config.featured_photos_visibility = "public"
    site_config.save()
    return photo


def _bytes(response) -> bytes:
    if hasattr(response, "streaming_content"):
        return b"".join(response.streaming_content)
    return response.content


# --------------------------------------------------------------------------
# 3a. `?size=` 的花样一律不得吐出原图
# --------------------------------------------------------------------------

SIZE_TRICKS = [
    "original",
    "ORIGINAL",
    "Original",
    " original ",
    "original\n",
    "../original",
    "thumb/../original",
    "orig",
    "full",
    "preview%00original",
    "",
    "0",
    "thumb,original",
    "[]",
    "__proto__",
]


@pytest.mark.parametrize("size", SIZE_TRICKS)
def test_任何size花样都拿不到原图字节(api_client, featured, size):
    from urllib.parse import quote

    original = featured.original.read()
    featured.original.close()

    response = api_client.get(
        f"/api/v1/home/featured-photos/{featured.pk}/file/?size={quote(size, safe='')}"
    )
    assert response.status_code in (200, 400, 403, 404), response.status_code
    if response.status_code == 200:
        payload = _bytes(response)
        assert payload != original, f"size={size!r} 吐出了原图字节"
        assert len(payload) < len(original), f"size={size!r} 吐出的比原图还大，八成是原图"


def test_重复size参数也拿不到原图(api_client, featured):
    original = featured.original.read()
    featured.original.close()
    response = api_client.get(
        f"/api/v1/home/featured-photos/{featured.pk}/file/?size=thumb&size=original"
    )
    assert response.status_code == 200
    assert _bytes(response) != original


def test_字节出口只吐webp且带nosniff(api_client, featured):
    """媒体域上的存储型 XSS 靠的就是「声明成别的类型 + 浏览器嗅探」。"""
    response = api_client.get(f"/api/v1/home/featured-photos/{featured.pk}/file/?size=preview")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "inline" in response["Content-Disposition"]


# --------------------------------------------------------------------------
# 3b. 不在精选池里的照片，回答必须与「不存在」一模一样
# --------------------------------------------------------------------------


def test_未精选的公开照片与不存在的pk回答相同(api_client, public_photo, site_config):
    site_config.featured_photos_enabled = True
    site_config.featured_photos_visibility = "public"
    site_config.save()

    photo = public_photo()  # 没有 set_photo_featured
    real = api_client.get(f"/api/v1/home/featured-photos/{photo.pk}/file/")
    ghost = api_client.get("/api/v1/home/featured-photos/999999/file/")
    assert real.status_code == 404 and ghost.status_code == 404
    assert real.content == ghost.content, "未精选的照片与不存在的 pk 回答不同 → 泄露存在性"


def test_待审照片既勾不上也拿不到(api_client, staff_user, user_factory, site_config, public_photo):
    """预审模式下新上传的照片是 pending。它不该有任何一条进首页的路。"""
    from apps.gallery import services as gallery_services
    from apps.gallery.models import PHOTO_PENDING_REVIEW
    from apps.gallery.tests.conftest import photo_upload
    from apps.siteconfig.models import GALLERY_MODE_PRE_REVIEW

    seed = public_photo()  # 借它的团与 GM
    site_config.gallery_moderation_mode = GALLERY_MODE_PRE_REVIEW
    site_config.featured_photos_enabled = True
    site_config.featured_photos_visibility = "public"
    site_config.save()

    pending = gallery_services.upload_photo(
        seed.uploader, seed.game, photo_upload(name="待审.jpg"), caption="待审合影"
    )
    assert pending.status == PHOTO_PENDING_REVIEW

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/featured-photos/",
        {"photo": pending.pk, "is_featured": True},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "photo_not_public"

    api_client.force_authenticate(None)
    assert api_client.get(f"/api/v1/home/featured-photos/{pending.pk}/file/").status_code == 404
    body = api_client.get("/api/v1/home/").json()
    assert all(row["id"] != pending.pk for row in body["featured_photos"]["results"])


def test_驳回的照片同样进不了首页(api_client, staff_user, site_config, public_photo):
    from apps.gallery import services as gallery_services
    from apps.gallery.models import PHOTO_PENDING_REVIEW
    from apps.gallery.tests.conftest import photo_upload
    from apps.siteconfig.models import GALLERY_MODE_PRE_REVIEW

    seed = public_photo()
    site_config.gallery_moderation_mode = GALLERY_MODE_PRE_REVIEW
    site_config.featured_photos_enabled = True
    site_config.featured_photos_visibility = "public"
    site_config.save()

    photo = gallery_services.upload_photo(
        seed.uploader, seed.game, photo_upload(name="驳回.jpg"), caption="驳回"
    )
    assert photo.status == PHOTO_PENDING_REVIEW
    gallery_services.reject_photo(photo, reason="不合适")

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/featured-photos/", {"photo": photo.pk, "is_featured": True}, format="json"
    )
    assert response.status_code == 400
    api_client.force_authenticate(None)
    assert api_client.get(f"/api/v1/home/featured-photos/{photo.pk}/file/").status_code == 404


# --------------------------------------------------------------------------
# 3c. 站主把「公开」收回
# --------------------------------------------------------------------------


def test_站主经API把public收回members后游客立刻断流(api_client, staff_user, featured):
    """真实操作：站主发现照片墙不该对游客开，去首页编辑模式里改回 members。

    配置是带缓存的单例（`siteconfig.services.get_config`），收回公开必须当场生效。
    """
    url = f"/api/v1/home/featured-photos/{featured.pk}/file/"
    assert api_client.get(url).status_code == 200

    api_client.force_authenticate(staff_user)
    response = api_client.patch(
        "/api/v1/home/admin/config/", {"featured_photos_visibility": "members"}, format="json"
    )
    assert response.status_code == 200, response.content[:300]

    api_client.force_authenticate(None)
    assert api_client.get(url).status_code == 404, "收回公开后游客还能拿到照片字节"
    body = api_client.get("/api/v1/home/").json()
    assert body["featured_photos"]["visible"] is False
    assert body["featured_photos"]["results"] == []


def test_站主经API关掉开关后游客立刻断流(api_client, staff_user, featured):
    url = f"/api/v1/home/featured-photos/{featured.pk}/file/"
    assert api_client.get(url).status_code == 200
    api_client.force_authenticate(staff_user)
    assert api_client.patch(
        "/api/v1/home/admin/config/", {"featured_photos_enabled": False}, format="json"
    ).status_code == 200
    api_client.force_authenticate(None)
    assert api_client.get(url).status_code == 404


@pytest.mark.parametrize("value", ["everyone", "PUBLIC", "Public", "", "members ", "public;", None, 1])
def test_可见范围只收两个合法值(api_client, staff_user, site_config, value):
    """乱值必须 400；绝不允许「存进去后被当成非 members 于是等同 public」。"""
    api_client.force_authenticate(staff_user)
    response = api_client.patch(
        "/api/v1/home/admin/config/", {"featured_photos_visibility": value}, format="json"
    )
    assert response.status_code == 400, f"{value!r} 被接受了"
    site_config.refresh_from_db()
    assert site_config.featured_photos_visibility in ("public", "members")


# --------------------------------------------------------------------------
# 3d. 公开响应体的泄露面
# --------------------------------------------------------------------------


def test_首页响应体不含邮箱存储路径与上传者(api_client, featured, announcement_factory, user_factory):
    """一份「整段文本」的体检：邮箱、媒体存储路径、上传者昵称都不许出现。"""
    announcement_factory(title="红队公告", body="正文")
    raw = api_client.get("/api/v1/home/").content.decode()

    assert "@" not in raw, "首页响应体里出现了 @（八成是邮箱）"
    for needle in (
        featured.original.name,
        featured.thumbnail.name,
        featured.preview.name,
        "protected/",
        "/media/gallery",
        featured.uploader.nickname,
        featured.uploader.email or "___no_email___",
    ):
        assert needle not in raw, f"首页响应体里出现了 {needle!r}"

    body = json.loads(raw)
    for row in body["featured_photos"]["results"]:
        assert set(row) == {
            "id", "caption", "game_id", "game_title", "width", "height",
            "thumbnail_url", "preview_url",
        }, f"精选照片多带了字段：{sorted(row)}"
        assert row["thumbnail_url"].startswith("/api/v1/home/featured-photos/")
        assert row["preview_url"].startswith("/api/v1/home/featured-photos/")


def test_members范围下首页连照片id都不给(api_client, featured, site_config):
    """`visible=False` 时不能只是「不给字节」——连有几张、id 是多少都不该漏。"""
    site_config.featured_photos_visibility = "members"
    site_config.save()
    body = api_client.get("/api/v1/home/").json()
    assert body["featured_photos"]["visible"] is False
    assert body["featured_photos"]["results"] == []
    assert str(featured.pk) not in json.dumps(body["featured_photos"])


def test_公告历史与首页都不吐作者邮箱(api_client, user_factory, announcement_factory):
    author = user_factory(nickname="公告作者", email="announcer@example.com")
    announcement_factory(title="公开的公告", body="正文", author=author)

    for url in ("/api/v1/home/", "/api/v1/announcements/"):
        raw = api_client.get(url).content.decode()
        assert "announcer@example.com" not in raw
        assert "@" not in raw, f"{url} 响应体里出现了 @"


def test_禁言用户仍属于登录成员可见范围(api_client, featured, site_config, user_factory):
    """禁言只限制「发言」，不该连首页照片都看不到 —— 反过来也不该给游客开口子。"""
    from apps.accounts.services import mute_user

    site_config.featured_photos_visibility = "members"
    site_config.save()
    muted = user_factory(nickname="被禁言的看客")
    mute_user(muted, reason="刷屏")
    api_client.force_authenticate(muted)
    assert api_client.get(f"/api/v1/home/featured-photos/{featured.pk}/file/").status_code == 200
