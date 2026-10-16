"""站点配置公开接口：游客可读，且不得泄露运维字段。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

# 这些字段属于运维参数或算法内部值，公开接口里一个都不许出现
FORBIDDEN_FIELDS = {
    "auto_close_days",
    "auto_close_reminder_days",
    "level_overwhelmingly_positive_min",
    "level_mostly_positive_min",
    "level_overwhelmingly_negative_dislike_min",
    "level_mostly_negative_dislike_min",
    "id",
    "created_at",
    "updated_at",
}


def test_游客可读站点配置(api_client):
    response = api_client.get("/api/v1/siteconfig/")
    assert response.status_code == 200
    data = response.json()
    assert data["site_name"]
    assert data["like_feature_enabled"] is True
    assert data["invite_code_required"] is False
    assert data["rule_system_presets"] == ["FU", "COC", "DND", "三角机构"]


def test_公开配置不含运维与算法字段(api_client):
    data = api_client.get("/api/v1/siteconfig/").json()
    assert FORBIDDEN_FIELDS.isdisjoint(data.keys())


def test_单例与缓存失效(db):
    from apps.siteconfig.models import SiteConfig
    from apps.siteconfig.services import get_config

    first = get_config()
    assert first.pk == 1
    first.site_name = "改过的站名"
    first.save()
    assert SiteConfig.objects.count() == 1
    assert get_config().site_name == "改过的站名"


def test_备案号对游客可见且默认为空(api_client, site_config):
    """ICP 备案号是页脚必须展示的合规信息（国内部署前置），游客当然要看得见。"""
    data = api_client.get("/api/v1/siteconfig/").json()
    assert data["icp_beian"] == ""

    site_config.icp_beian = "京ICP备12345678号-1"
    site_config.save()

    assert api_client.get("/api/v1/siteconfig/").json()["icp_beian"] == "京ICP备12345678号-1"


def test_公开字段集合与架构白名单一致(api_client):
    """业务规则与安全约束。"""
    expected = {
        "site_name",
        "announcement",
        "icp_beian",
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
    assert set(api_client.get("/api/v1/siteconfig/").json()) == expected
