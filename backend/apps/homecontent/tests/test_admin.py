"""Django 后台冒烟：三张新表 + 被改过的 Photo / SiteConfig 页面都要能渲染。

后台配置的错（fieldsets 里写了不存在的字段、readonly 与 fieldsets 打架、
`list_editable` 不在 `list_display` 里）**不会被 `manage.py check` 抓到**，
只在真正渲染那一页时炸。这组用例就是替站主先点一遍。
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

ADMIN = "/" + settings.ADMIN_URL.strip("/") + "/"


@pytest.fixture
def admin_client(api_client, user_factory):
    from rest_framework.test import APIClient

    superuser = user_factory(nickname="后台管理员", email="admin@example.com")
    superuser.is_staff = True
    superuser.is_superuser = True
    superuser.save(update_fields=["is_staff", "is_superuser"])
    client = APIClient()
    client.force_login(superuser)
    return client


@pytest.mark.parametrize(
    "model",
    ["rulesystempreset", "quickentry", "siteannouncement"],
)
def test_站长内容三张表的后台页可渲染(admin_client, model):
    listing = admin_client.get(f"{ADMIN}homecontent/{model}/")
    assert listing.status_code == 200
    add = admin_client.get(f"{ADMIN}homecontent/{model}/add/")
    assert add.status_code == 200


def test_规则预设详情页带三档缩略预览(admin_client):
    from apps.homecontent.models import RuleSystemPreset
    from apps.homecontent.services import set_preset_image
    from apps.homecontent.tests.conftest import image_upload

    preset = RuleSystemPreset.objects.first()
    set_preset_image(preset, image_upload())
    page = admin_client.get(f"{ADMIN}homecontent/rulesystempreset/{preset.pk}/change/")
    assert page.status_code == 200
    assert preset.image_thumb.url.encode() in page.content


def test_相册与站点配置页在改过字段后仍可渲染(admin_client, public_photo):
    photo = public_photo()
    assert admin_client.get(f"{ADMIN}gallery/photo/").status_code == 200
    assert admin_client.get(f"{ADMIN}gallery/photo/{photo.pk}/change/").status_code == 200
    # 站点配置的列表页会 302 跳到唯一那行
    listing = admin_client.get(f"{ADMIN}siteconfig/siteconfig/")
    assert listing.status_code == 302
    assert admin_client.get(listing["Location"]).status_code == 200


def test_后台建公告会推送一轮(admin_client, user_factory):
    from apps.notifications import events
    from apps.notifications.models import Notification

    reader = user_factory(nickname="后台公告收件人")
    url = reverse("admin:homecontent_siteannouncement_add")
    response = admin_client.post(
        url,
        {
            "title": "后台发的公告",
            "body": "正文",
            "published_at_0": "2026-09-21",
            "published_at_1": "10:00:00",
            "is_active": "on",
        },
    )
    assert response.status_code == 302, response.content[:500]
    assert Notification.objects.filter(
        recipient=reader, event=events.SITE_ANNOUNCEMENT
    ).count() == 1


def test_后台不能把非公开照片勾成精选(admin_client, public_photo):
    from apps.gallery import services

    photo = services.take_down_photo(public_photo(), reason="先下架")
    response = admin_client.post(
        f"{ADMIN}gallery/photo/{photo.pk}/change/",
        {"status": photo.status, "caption": "", "taken_down_reason": "", "is_featured": "on"},
    )
    assert response.status_code == 200  # 表单校验不过 → 原页重渲染，不是 302
    photo.refresh_from_db()
    assert photo.is_featured is False
