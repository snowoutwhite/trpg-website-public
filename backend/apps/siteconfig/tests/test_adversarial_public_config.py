"""对抗性测试 · 站点配置公开接口：只读、字段白名单、运维参数不外露。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

CONFIG = "/api/v1/siteconfig/"


PUBLIC_FIELDS = {
    "site_name",
    "announcement",
    "icp_beian",  # 页脚备案号，游客也要看得见（W5）
    "like_feature_enabled",
    "invite_code_required",
    "gallery_moderation_mode",
    "rule_system_presets",
    "footer_tagline",
    "like_level_publish_threshold",
    "review_window_days",
    "gallery_upload_window_days",
    "gm_auto_promote_threshold",
}

# 运维参数与内部状态：一个都不许出现在公开响应里。
FORBIDDEN_FIELDS = {
    "id",
    "pk",
    "created_at",
    "updated_at",
    "auto_close_days",
    "auto_close_reminder_days",
    "level_overwhelmingly_positive_min",
    "level_mostly_positive_min",
    "level_overwhelmingly_negative_dislike_min",
    "level_mostly_negative_dislike_min",
}


def test_public_config_field_set_is_exactly_the_whitelist(api_client):
    data = api_client.get(CONFIG).json()
    assert set(data) == PUBLIC_FIELDS, f"公开字段集合漂移：多出 {set(data) - PUBLIC_FIELDS}"


def test_public_config_hides_level_boundaries_and_ops_params(api_client):
    """五档边界是「可被反推的评分规则」，运维天数是内部节奏，都不对游客公开。"""
    data = api_client.get(CONFIG).json()
    leaked = FORBIDDEN_FIELDS & set(data)
    assert not leaked, f"公开接口泄露了内部项：{sorted(leaked)}"


def test_public_config_is_read_only_for_everyone(api_client, user_factory):
    """站主之外没有任何人能改配置；站主也只能走后台，不走 API。"""
    payloads = {"site_name": "被改名的站", "invite_code_required": True}

    for method in ("post", "put", "patch", "delete"):
        response = getattr(api_client, method)(CONFIG, payloads, format="json")
        assert response.status_code == 405, f"游客 {method} → {response.status_code}"

    user = user_factory(nickname="普通用户", email="plain@example.com")
    api_client.force_authenticate(user)
    for method in ("post", "put", "patch", "delete"):
        response = getattr(api_client, method)(CONFIG, payloads, format="json")
        assert response.status_code == 405, f"普通用户 {method} → {response.status_code}"

    staff = user_factory(nickname="站主用户", email="owner@example.com")
    staff.is_staff = True
    staff.is_superuser = True
    staff.save(update_fields=["is_staff", "is_superuser"])
    api_client.force_authenticate(staff)
    for method in ("post", "put", "patch", "delete"):
        assert getattr(api_client, method)(CONFIG, payloads, format="json").status_code == 405

    from apps.siteconfig.services import get_config

    assert get_config().site_name != "被改名的站"


def test_public_config_ignores_injected_query_params(api_client, site_config):
    """不能靠 query 参数把隐藏字段要出来。"""
    site_config.auto_close_days = 7
    site_config.save()
    for query in ["?fields=__all__", "?fields=auto_close_days", "?expand=1", "?format=api"]:
        data = api_client.get(CONFIG + query)
        assert data.status_code in (200, 404), query
        if data.status_code == 200 and data["Content-Type"].startswith("application/json"):
            assert set(data.json()) == PUBLIC_FIELDS, query


def test_singleton_cannot_be_deleted(site_config):
    with pytest.raises(RuntimeError):
        site_config.delete()


def test_singleton_cannot_be_added_or_deleted_from_admin(site_config, user_factory, rf):
    """后台也不能新增第二行、不能删除唯一那行。"""
    from django.contrib.admin.sites import AdminSite

    from apps.siteconfig.admin import SiteConfigAdmin
    from apps.siteconfig.models import SiteConfig

    staff = user_factory(nickname="站主admin", email="owner-admin@example.com")
    staff.is_staff = True
    staff.is_superuser = True
    staff.save(update_fields=["is_staff", "is_superuser"])

    request = rf.get("/")
    request.user = staff
    admin_instance = SiteConfigAdmin(SiteConfig, AdminSite())
    assert admin_instance.has_add_permission(request) is False
    assert admin_instance.has_delete_permission(request, site_config) is False


def test_config_cache_is_invalidated_on_write(api_client, site_config):
    """配置带缓存：站主改完必须立刻对外生效，不能一直返回旧值。"""
    assert api_client.get(CONFIG).json()["site_name"] == site_config.site_name

    site_config.site_name = "新站名XYZ"
    site_config.save()

    assert api_client.get(CONFIG).json()["site_name"] == "新站名XYZ"
