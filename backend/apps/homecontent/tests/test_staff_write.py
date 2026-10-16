"""站主写接口：字段更新（PATCH）、图片上传（multipart）、精选照片勾选。"""

from __future__ import annotations

import pytest

from apps.homecontent.tests.conftest import image_upload, png_bytes

pytestmark = pytest.mark.django_db


def test_站主改首页文案(api_client, staff_user, site_config):
    api_client.force_authenticate(staff_user)
    response = api_client.patch(
        "/api/v1/home/admin/config/",
        {"home_section3_title": "今晚开的团", "footer_tagline": "骰子落下之处"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["home_section3_title"] == "今晚开的团"

    body = api_client.get("/api/v1/home/").json()
    assert body["site"]["section3"]["title"] == "今晚开的团"
    assert body["site"]["footer_tagline"] == "骰子落下之处"


def test_站主改规则预设并自动同步镜像(api_client, staff_user):
    from apps.homecontent.models import RuleSystemPreset

    api_client.force_authenticate(staff_user)
    preset = RuleSystemPreset.objects.get(name="FU")
    response = api_client.patch(
        f"/api/v1/home/admin/rule-presets/{preset.pk}/",
        {"name": "Fabula Ultima", "tagline": "共写一段物语"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["tagline"] == "共写一段物语"
    assert "Fabula Ultima" in api_client.get("/api/v1/siteconfig/").json()["rule_system_presets"]


def test_站主新建与删除规则预设(api_client, staff_user):
    api_client.force_authenticate(staff_user)
    created = api_client.post(
        "/api/v1/home/admin/rule-presets/",
        {"name": "PBTA", "title": "被驱动的世界", "sort": 90},
        format="json",
    )
    assert created.status_code == 201
    pk = created.json()["id"]
    assert "PBTA" in api_client.get("/api/v1/siteconfig/").json()["rule_system_presets"]

    assert api_client.delete(f"/api/v1/home/admin/rule-presets/{pk}/").status_code == 204
    assert "PBTA" not in api_client.get("/api/v1/siteconfig/").json()["rule_system_presets"]


def test_规则预设配图一次生成三档且都是webp(api_client, staff_user):
    from apps.homecontent.models import RuleSystemPreset

    api_client.force_authenticate(staff_user)
    preset = RuleSystemPreset.objects.get(name="COC")
    response = api_client.post(
        f"/api/v1/home/admin/rule-presets/{preset.pk}/image/",
        {"file": image_upload()},
        format="multipart",
    )
    assert response.status_code == 200
    tiers = response.json()["image"]
    assert tiers["full"] and tiers["card"] and tiers["thumb"]
    assert all(url.endswith(".webp") for url in tiers.values())
    # 三档互不相同，且落在公开 media 目录（不是 protected/）
    assert len(set(tiers.values())) == 3
    assert all("/protected/" not in url for url in tiers.values())

    preset.refresh_from_db()
    from PIL import Image

    with Image.open(preset.image_thumb.path) as image:
        assert image.format == "WEBP"
        assert max(image.size) <= 400


def test_配图剥掉EXIF与GPS(api_client, staff_user):
    from PIL import Image

    from apps.gallery.tests.conftest import exif_with_gps, make_image_bytes, read_exif
    from apps.homecontent.models import RuleSystemPreset

    api_client.force_authenticate(staff_user)
    preset = RuleSystemPreset.objects.get(name="DND")
    raw = make_image_bytes(exif=exif_with_gps())
    assert read_exif(raw), "夹具本身要带 EXIF，否则这条用例什么都没证明"

    api_client.post(
        f"/api/v1/home/admin/rule-presets/{preset.pk}/image/",
        {"file": image_upload(data=raw)},
        format="multipart",
    )
    preset.refresh_from_db()
    for field in (preset.image_full, preset.image_card, preset.image_thumb):
        with open(field.path, "rb") as handle:
            assert not read_exif(handle.read())
    assert Image.open(preset.image_full.path).format == "WEBP"


def test_换图会删掉旧文件(api_client, staff_user):
    import os

    from apps.homecontent.models import RuleSystemPreset

    api_client.force_authenticate(staff_user)
    preset = RuleSystemPreset.objects.get(name="DND")
    url = f"/api/v1/home/admin/rule-presets/{preset.pk}/image/"
    api_client.post(url, {"file": image_upload()}, format="multipart")
    preset.refresh_from_db()
    old_path = preset.image_full.path

    api_client.post(url, {"file": image_upload(data=png_bytes((900, 600)), name="新图.png")}, format="multipart")
    preset.refresh_from_db()
    assert preset.image_full.path != old_path
    assert not os.path.exists(old_path)


def test_快速选择配图只有一档(api_client, staff_user):
    from apps.homecontent.models import QuickEntry

    api_client.force_authenticate(staff_user)
    entry = QuickEntry.objects.get(key="recruit")
    response = api_client.post(
        f"/api/v1/home/admin/quick-entries/{entry.pk}/image/",
        {"file": image_upload()},
        format="multipart",
    )
    assert response.status_code == 200
    assert response.json()["image"].endswith(".webp")


def test_站主改快速选择文案与路由(api_client, staff_user):
    from apps.homecontent.models import QuickEntry

    api_client.force_authenticate(staff_user)
    entry = QuickEntry.objects.get(key="cards")
    response = api_client.patch(
        f"/api/v1/home/admin/quick-entries/{entry.pk}/",
        {"button_text": "看看角色", "route": "/cards?rule_system=COC"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["route"] == "/cards?rule_system=COC"


def test_站主建公告即推送且列表可见(api_client, staff_user, user_factory):
    from apps.notifications import events
    from apps.notifications.models import Notification

    reader = user_factory(nickname="收公告的")
    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/announcements/",
        {"title": "元旦停站维护", "body": "1 月 1 日 02:00-04:00"},
        format="json",
    )
    assert response.status_code == 201
    assert Notification.objects.filter(
        recipient=reader, event=events.SITE_ANNOUNCEMENT
    ).count() == 1

    api_client.force_authenticate(None)
    assert api_client.get("/api/v1/announcements/").json()["count"] == 1


def test_未生效的公告先不推等改成生效再推(api_client, staff_user, user_factory):
    from apps.notifications import events
    from apps.notifications.models import Notification

    reader = user_factory(nickname="等公告的")
    api_client.force_authenticate(staff_user)
    created = api_client.post(
        "/api/v1/home/admin/announcements/",
        {"title": "草稿", "body": "还没想好", "is_active": False},
        format="json",
    )
    assert created.status_code == 201
    assert Notification.objects.filter(recipient=reader, event=events.SITE_ANNOUNCEMENT).count() == 0

    pk = created.json()["id"]
    api_client.patch(f"/api/v1/home/admin/announcements/{pk}/", {"is_active": True}, format="json")
    assert Notification.objects.filter(recipient=reader, event=events.SITE_ANNOUNCEMENT).count() == 1


def test_站主勾选精选照片后首页对成员可见(api_client, staff_user, user_factory, public_photo, site_config):
    photo = public_photo()
    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/featured-photos/",
        {"photo": photo.pk, "is_featured": True},
        format="json",
    )
    assert response.status_code == 200
    assert response.json() == {"id": photo.pk, "is_featured": True}

    site_config.featured_photos_enabled = True
    site_config.save()

    # 游客：默认可见范围是 members，拿不到
    api_client.force_authenticate(None)
    guest = api_client.get("/api/v1/home/").json()["featured_photos"]
    assert guest["visible"] is False and guest["results"] == []

    # 登录成员：拿得到，且只给 thumb/preview 的鉴权路径
    api_client.force_authenticate(user_factory(nickname="成员"))
    member = api_client.get("/api/v1/home/").json()["featured_photos"]
    assert member["visible"] is True
    assert [row["id"] for row in member["results"]] == [photo.pk]
    row = member["results"][0]
    assert set(row) == {
        "id", "caption", "game_id", "game_title", "width", "height", "thumbnail_url", "preview_url"
    }
    assert row["thumbnail_url"].endswith(f"/api/v1/home/featured-photos/{photo.pk}/file/?size=thumb")


def test_可见范围public时游客也能拿到照片字节(api_client, staff_user, public_photo, site_config):
    from apps.homecontent import services

    photo = public_photo()
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True
    site_config.featured_photos_visibility = "public"
    site_config.save()

    response = api_client.get(f"/api/v1/home/featured-photos/{photo.pk}/file/?size=preview")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "inline" in response["Content-Disposition"]


def test_照片下架后自动取消精选(db, public_photo):
    from apps.gallery import services as gallery_services
    from apps.homecontent import services

    photo = public_photo()
    services.set_photo_featured(photo, True)
    gallery_services.take_down_photo(photo, reason="站主在后台下架")
    photo.refresh_from_db()
    assert photo.is_featured is False
    assert services.featured_photos().count() == 0


def test_站主总览接口给出可编辑全量(api_client, staff_user, announcement_factory):
    announcement_factory(title="草稿公告", is_active=False)
    api_client.force_authenticate(staff_user)
    body = api_client.get("/api/v1/home/admin/").json()
    assert set(body) == {"config", "rule_presets", "quick_entries", "announcements"}
    assert len(body["rule_presets"]) == 4
    assert len(body["quick_entries"]) == 6
    # 站主视角能看到未生效的公告与推送状态
    assert body["announcements"][0]["title"] == "草稿公告"
    assert body["announcements"][0]["is_active"] is False
    assert body["announcements"][0]["notified_at"] is None
