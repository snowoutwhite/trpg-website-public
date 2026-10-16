"""业务规则与安全约束。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def code_of(response) -> str:
    return response.json()["error"]["code"]


@pytest.fixture
def targets(db):
    """把每一条 staff 写接口都展开成 (method, url, payload)。"""
    from django.utils import timezone

    from apps.homecontent.models import QuickEntry, RuleSystemPreset, SiteAnnouncement

    preset = RuleSystemPreset.objects.first()
    entry = QuickEntry.objects.first()
    announcement = SiteAnnouncement.objects.create(
        title="红队公告", body="正文", published_at=timezone.now()
    )
    return [
        ("get", "/api/v1/home/admin/", None),
        ("patch", "/api/v1/home/admin/config/", {"site_name": "被改了"}),
        ("get", "/api/v1/home/admin/rule-presets/", None),
        ("post", "/api/v1/home/admin/rule-presets/", {"name": "偷建的"}),
        ("patch", f"/api/v1/home/admin/rule-presets/{preset.pk}/", {"title": "偷改的"}),
        ("delete", f"/api/v1/home/admin/rule-presets/{preset.pk}/", None),
        ("get", "/api/v1/home/admin/quick-entries/", None),
        ("post", "/api/v1/home/admin/quick-entries/", {"key": "x", "label": "偷建", "route": "/"}),
        ("patch", f"/api/v1/home/admin/quick-entries/{entry.pk}/", {"label": "偷改的"}),
        ("delete", f"/api/v1/home/admin/quick-entries/{entry.pk}/", None),
        ("get", "/api/v1/home/admin/announcements/", None),
        ("post", "/api/v1/home/admin/announcements/", {"title": "假公告", "body": "全站可见"}),
        ("patch", f"/api/v1/home/admin/announcements/{announcement.pk}/", {"title": "偷改"}),
        ("delete", f"/api/v1/home/admin/announcements/{announcement.pk}/", None),
        ("get", "/api/v1/home/admin/featured-photos/", None),
        ("post", "/api/v1/home/admin/featured-photos/", {"photo": 1, "is_featured": True}),
    ]


def _call(api_client, method, url, payload):
    call = getattr(api_client, method)
    return call(url, payload, format="json") if payload else call(url)


def test_游客打全部staff端点含pk支线都是401(api_client, targets):
    wrong = {}
    for method, url, payload in targets:
        response = _call(api_client, method, url, payload)
        if response.status_code != 401 or code_of(response) != "not_authenticated":
            wrong[f"{method.upper()} {url}"] = response.status_code
    assert not wrong, f"游客没被挡在 401：{wrong}"


def test_普通用户打全部staff端点含pk支线都是403(api_client, user_factory, targets):
    api_client.force_authenticate(user_factory(nickname="路人甲"))
    wrong = {}
    for method, url, payload in targets:
        response = _call(api_client, method, url, payload)
        if response.status_code != 403:
            wrong[f"{method.upper()} {url}"] = response.status_code
    assert not wrong, f"普通用户没被挡在 403：{wrong}"


def test_GM打全部staff端点含pk支线都是403(api_client, user_factory, targets):
    gm = user_factory(nickname="想改首页的GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    api_client.force_authenticate(gm)
    wrong = {}
    for method, url, payload in targets:
        response = _call(api_client, method, url, payload)
        if response.status_code != 403:
            wrong[f"{method.upper()} {url}"] = response.status_code
    assert not wrong, f"GM 没被挡在 403：{wrong}"


def test_注销掉的老站主写不了站长内容(api_client, staff_user, targets):
    """`is_staff=True` 但 `is_active=False`：注销过的账号仍留着 staff 位。

    这条状态在 `IsAuthenticatedAndActive` 里对应 403 `account_deactivated`，
    与封禁那条不同 —— 封禁号会被先判成 `account_banned`。
    """
    from apps.accounts.services import deactivate_account

    deactivate_account(staff_user)
    staff_user.refresh_from_db()
    assert staff_user.is_staff is True and staff_user.is_active is False

    api_client.force_authenticate(staff_user)
    wrong = {}
    for method, url, payload in targets:
        response = _call(api_client, method, url, payload)
        if response.status_code != 403 or code_of(response) != "account_deactivated":
            wrong[f"{method.upper()} {url}"] = (response.status_code, response.content[:120])
    assert not wrong, f"注销的站主没被挡住：{wrong}"


def test_被封禁的站主打全部端点都是403封禁(api_client, staff_user, targets):
    from apps.accounts.services import ban_user

    ban_user(staff_user, reason="滥用")
    api_client.force_authenticate(staff_user)
    wrong = {}
    for method, url, payload in targets:
        response = _call(api_client, method, url, payload)
        if response.status_code != 403 or code_of(response) != "account_banned":
            wrong[f"{method.upper()} {url}"] = (response.status_code, response.content[:120])
    assert not wrong, f"封禁的站主没被挡住：{wrong}"


# --------------------------------------------------------------------------
# PATCH config 的白名单
# --------------------------------------------------------------------------

#: 一律不该被首页编辑模式的 PATCH 改动的字段。挑的都是「改了会出事」的：
#: 相册审核模式决定真人照片什么时候进公开区；邀请码开关决定注册门槛；
#: 赞开关决定评价入口；`rule_system_presets` 是预设表同步出来的只读镜像。
OFF_WHITELIST = {
    "like_feature_enabled": False,
    "invite_code_required": True,
    "gallery_moderation_mode": "post_report",
    "auto_close_days": 999,
    "gm_auto_promote_threshold": 1,
    "review_window_days": 999,
    "icp_beian": "京ICP备00000000号",
    "rule_system_presets": ["黑进来的"],
    "id": 99,
    "pk": 99,
}


def test_站主PATCH白名单外字段一律不落库(api_client, staff_user, site_config):
    api_client.force_authenticate(staff_user)
    before = {field: getattr(site_config, field) for field in OFF_WHITELIST if field not in ("id", "pk")}

    payload = dict(OFF_WHITELIST)
    payload["home_section3_title"] = "白名单内的正常字段"
    response = api_client.patch("/api/v1/home/admin/config/", payload, format="json")
    assert response.status_code == 200, response.content[:300]

    site_config.refresh_from_db()
    changed = {
        field: (old, getattr(site_config, field))
        for field, old in before.items()
        if getattr(site_config, field) != old
    }
    assert not changed, f"白名单外的字段被改了：{changed}"
    assert site_config.home_section3_title == "白名单内的正常字段"
    assert site_config.pk == 1


def test_PATCHconfig的响应体不外泄运维参数(api_client, staff_user, site_config):
    """响应体就是编辑表单的回填源；多吐一个运维字段，前端就会把它画成可编辑格。"""
    api_client.force_authenticate(staff_user)
    body = api_client.patch(
        "/api/v1/home/admin/config/", {"home_section4_title": "留下的故事"}, format="json"
    ).json()
    leaked = sorted(set(body) & set(OFF_WHITELIST))
    assert not leaked, f"响应体里出现了不该编辑的字段：{leaked}"


def test_新建预设时塞图片字段与id都不生效(api_client, staff_user):
    """图片只能走 multipart 的专用接口（那里才有魔数/像素/EXIF 三道闸）。"""
    from apps.homecontent.models import RuleSystemPreset

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/rule-presets/",
        {
            "name": "红队预设",
            "id": 12345,
            "image_full": "homecontent/../../etc/passwd",
            "image_card": "homecontent/evil.svg",
            "image_thumb": "/etc/passwd",
        },
        format="json",
    )
    assert response.status_code == 201, response.content[:300]
    preset = RuleSystemPreset.objects.get(name="红队预设")
    assert preset.pk != 12345
    assert not preset.image_full and not preset.image_card and not preset.image_thumb


def test_改公告时改不了推送记账字段(api_client, staff_user, announcement_factory, user_factory):
    """`notified_at` / `notified_count` 是幂等锚。能从接口把它抹掉 = 能重复轰炸全站。"""
    from apps.notifications import events
    from apps.notifications.models import Notification

    reader = user_factory(nickname="收件人")
    announcement = announcement_factory(title="第一次")
    from apps.homecontent import services

    services.publish_announcement(announcement)
    first = Notification.objects.filter(recipient=reader, event=events.SITE_ANNOUNCEMENT).count()
    assert first == 1

    api_client.force_authenticate(staff_user)
    response = api_client.patch(
        f"/api/v1/home/admin/announcements/{announcement.pk}/",
        {"notified_at": None, "notified_count": 0, "title": "改个标题"},
        format="json",
    )
    assert response.status_code == 200, response.content[:300]
    announcement.refresh_from_db()
    assert announcement.notified_at is not None, "notified_at 被接口抹掉了 → 可重复推送全站"
    assert (
        Notification.objects.filter(recipient=reader, event=events.SITE_ANNOUNCEMENT).count() == 1
    )
