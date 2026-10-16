"""`GET /api/v1/home/`：一次把首页要的内容给全。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_游客可读首页内容且结构完整(api_client, seeded_home, site_config):
    response = api_client.get("/api/v1/home/")
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"site", "rule_presets", "quick_entries", "announcement", "featured_photos"}
    assert body["site"]["site_name"] == site_config.site_name
    assert body["site"]["footer_tagline"] == "让冒险者相遇"
    assert body["site"]["section3"]["kicker"] == "OPEN TABLES"
    assert body["site"]["section4"]["title"] == "留下的故事"
    assert body["announcement"] is None
    assert body["featured_photos"] == {
        "enabled": False,
        "visibility": "members",
        "visible": False,
        "results": [],
    }


def test_迁移预置了四条规则预设与六项快速选择(api_client):
    body = api_client.get("/api/v1/home/").json()

    names = [row["name"] for row in body["rule_presets"]]
    assert names == ["FU", "COC", "DND", "三角机构"]
    dnd = next(row for row in body["rule_presets"] if row["name"] == "DND")
    assert dnd["kicker"] == "DUNGEONS & DRAGONS"
    assert dnd["title"] == "龙与地下城"
    assert dnd["intro"]["hero"].startswith("掷下骰子")
    assert dnd["intro"]["body"] and dnd["intro"]["fit"]
    assert dnd["official_url"].startswith("https://")
    assert dnd["image"] == {"full": "", "card": "", "thumb": ""}  # 素材由站主自选上传

    keys = [row["key"] for row in body["quick_entries"]]
    assert keys == ["newbie", "recruit", "host", "resources", "reports", "cards"]
    newbie = body["quick_entries"][0]
    assert newbie["label"] == "我是新人"
    assert newbie["button_text"] == "阅读新人指南"
    assert newbie["route"] == "/guide"
    # 预览里的 <br> 落库时换成真正的换行符：文案字段一律纯文本，不进 v-html。
    assert "<br>" not in newbie["title"]
    assert "\n" in newbie["title"]


def test_规则预设名与站级JSON镜像一致(api_client):
    presets = api_client.get("/api/v1/home/").json()["rule_presets"]
    mirror = api_client.get("/api/v1/siteconfig/").json()["rule_system_presets"]
    assert [row["name"] for row in presets] == mirror


def test_改预设表会同步刷新JSON镜像(api_client, db):
    from apps.homecontent.models import RuleSystemPreset

    RuleSystemPreset.objects.create(name="PBTA", sort=99)
    assert api_client.get("/api/v1/siteconfig/").json()["rule_system_presets"][-1] == "PBTA"

    RuleSystemPreset.objects.get(name="PBTA").delete()
    assert "PBTA" not in api_client.get("/api/v1/siteconfig/").json()["rule_system_presets"]


def test_首页只给最新一条生效公告(api_client, announcement_factory):
    from datetime import timedelta

    from django.utils import timezone

    announcement_factory(title="旧公告", published_at=timezone.now() - timedelta(days=2))
    announcement_factory(title="新公告")
    announcement_factory(title="下架的", is_active=False)
    announcement_factory(title="预告", published_at=timezone.now() + timedelta(days=1))

    body = api_client.get("/api/v1/home/").json()
    assert body["announcement"]["title"] == "新公告"
    # 游客没有已读状态
    assert body["announcement"]["is_read"] is None
    assert body["announcement"]["notification_id"] is None


def test_登录用户能看到公告是否已读(api_client, user_factory, staff_user):
    from django.utils import timezone

    from apps.homecontent import services
    from apps.homecontent.models import SiteAnnouncement

    reader = user_factory(nickname="读公告的")
    announcement = SiteAnnouncement.objects.create(
        title="场地变更", body="改到二楼", published_at=timezone.now(), author=staff_user
    )
    services.publish_announcement(announcement)

    api_client.force_authenticate(reader)
    body = api_client.get("/api/v1/home/").json()
    assert body["announcement"]["is_read"] is False
    notification_id = body["announcement"]["notification_id"]
    assert notification_id

    assert api_client.post("/api/v1/notifications/read/", {"ids": [notification_id]}, format="json").status_code == 200
    assert api_client.get("/api/v1/home/").json()["announcement"]["is_read"] is True


def test_公告历史页分页且只列生效的(api_client, announcement_factory):
    from datetime import timedelta

    from django.utils import timezone

    for i in range(3):
        announcement_factory(title=f"公告{i}", published_at=timezone.now() - timedelta(days=i))
    announcement_factory(title="已下架", is_active=False)
    announcement_factory(title="预告", published_at=timezone.now() + timedelta(days=5))

    body = api_client.get("/api/v1/announcements/").json()
    assert body["count"] == 3
    assert [row["title"] for row in body["results"]] == ["公告0", "公告1", "公告2"]
    assert set(body["results"][0]) == {
        "id", "title", "body", "published_at", "author", "is_read", "notification_id"
    }


def test_发布公告给全站活跃用户各推一条(db, user_factory, staff_user, announcement_factory):
    from apps.accounts.services import ban_user, deactivate_account
    from apps.homecontent import services
    from apps.notifications import events
    from apps.notifications.models import Notification

    alive = user_factory(nickname="在站的")
    banned = user_factory(nickname="被封的")
    gone = user_factory(nickname="注销的")
    ban_user(banned)
    deactivate_account(gone)

    announcement = announcement_factory(title="全员通知")
    count = services.publish_announcement(announcement)

    recipients = set(
        Notification.objects.filter(event=events.SITE_ANNOUNCEMENT).values_list(
            "recipient_id", flat=True
        )
    )
    assert alive.pk in recipients
    assert staff_user.pk in recipients
    assert banned.pk not in recipients
    assert gone.pk not in recipients
    assert count == len(recipients)

    announcement.refresh_from_db()
    assert announcement.notified_at is not None
    assert announcement.notified_count == count


def test_广播按邮件偏好发信(db, user_factory, announcement_factory):
    from django.core import mail

    from apps.homecontent import services
    from apps.notifications.models import EmailPreference

    wants = user_factory(nickname="要邮件的", email="want-broadcast@example.com")
    EmailPreference.objects.create(user=wants, email_enabled=True)
    user_factory(nickname="不要邮件的", email="no-broadcast@example.com")

    services.publish_announcement(announcement_factory(title="要发信的公告"))

    assert [m.to for m in mail.outbox] == [["want-broadcast@example.com"]]
