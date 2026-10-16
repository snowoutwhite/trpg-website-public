"""业务规则与安全约束。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

pytestmark = pytest.mark.django_db

ADMIN = "/" + settings.ADMIN_URL.strip("/") + "/"


def _count(user):
    from apps.notifications import events
    from apps.notifications.models import Notification

    return Notification.objects.filter(recipient=user, event=events.SITE_ANNOUNCEMENT).count()


# --------------------------------------------------------------------------
# 4a. 推送幂等
# --------------------------------------------------------------------------


def test_来回翻转生效状态十次也只推一轮(api_client, staff_user, user_factory):
    reader = user_factory(nickname="被翻来覆去的收件人")
    api_client.force_authenticate(staff_user)
    created = api_client.post(
        "/api/v1/home/admin/announcements/",
        {"title": "反复横跳", "body": "正文", "is_active": True},
        format="json",
    )
    assert created.status_code == 201
    pk = created.json()["id"]
    assert _count(reader) == 1

    for i in range(10):
        response = api_client.patch(
            f"/api/v1/home/admin/announcements/{pk}/", {"is_active": i % 2 == 1}, format="json"
        )
        assert response.status_code == 200, response.content[:200]
    assert _count(reader) == 1, "反复切 is_active 推出了不止一轮"


def test_把发布时间往前挪也不会再推(api_client, staff_user, user_factory):
    """`published_at` 是可改字段，改它不该重开幂等闸。"""
    reader = user_factory(nickname="收件人")
    api_client.force_authenticate(staff_user)
    pk = api_client.post(
        "/api/v1/home/admin/announcements/", {"title": "挪时间", "body": "正文"}, format="json"
    ).json()["id"]
    assert _count(reader) == 1

    for delta in (-3, -2, -1):
        api_client.patch(
            f"/api/v1/home/admin/announcements/{pk}/",
            {"published_at": (timezone.now() + timedelta(days=delta)).isoformat()},
            format="json",
        )
    assert _count(reader) == 1


def test_API发完再去后台保存一次也不重推(api_client, staff_user, user_factory):
    """两条写入路径（API + Django 后台）共用同一个幂等锚，混着用也只有一轮。"""
    from rest_framework.test import APIClient

    from apps.homecontent.models import SiteAnnouncement

    reader = user_factory(nickname="混着用的收件人")
    api_client.force_authenticate(staff_user)
    pk = api_client.post(
        "/api/v1/home/admin/announcements/", {"title": "混合路径", "body": "正文"}, format="json"
    ).json()["id"]
    assert _count(reader) == 1

    staff_user.is_superuser = True
    staff_user.save(update_fields=["is_superuser"])
    admin = APIClient()
    admin.force_login(staff_user)
    row = SiteAnnouncement.objects.get(pk=pk)
    response = admin.post(
        f"{ADMIN}homecontent/siteannouncement/{pk}/change/",
        {
            "title": "混合路径（改过）",
            "body": row.body,
            "published_at_0": row.published_at.strftime("%Y-%m-%d"),
            "published_at_1": row.published_at.strftime("%H:%M:%S"),
            "is_active": "on",
            "author": str(staff_user.pk),
        },
    )
    assert response.status_code == 302, response.content[:400]
    assert _count(reader) == 1, "后台再保存一次又推了一轮"


def test_预告到点之后必须推出去(api_client, staff_user, user_factory):
    """站主定了一条「预告」：发布时间在未来。到点之前不推 —— 这一半是对的。"""
    reader = user_factory(nickname="等预告的用户")
    api_client.force_authenticate(staff_user)
    future = timezone.now() + timedelta(hours=2)
    created = api_client.post(
        "/api/v1/home/admin/announcements/",
        {"title": "预告", "body": "下周六换场地", "published_at": future.isoformat()},
        format="json",
    )
    assert created.status_code == 201
    assert _count(reader) == 0, "还没到点就推了"

    # 时间到了：公告自己进了公开列表
    from apps.homecontent.models import SiteAnnouncement

    row = SiteAnnouncement.objects.get(pk=created.json()["id"])
    SiteAnnouncement.objects.filter(pk=row.pk).update(
        published_at=timezone.now() - timedelta(minutes=1)
    )
    api_client.force_authenticate(None)
    listed = api_client.get("/api/v1/announcements/").json()["results"]
    assert any(a["title"] == "预告" for a in listed), "到点后公告没进公开列表"
    assert _count(reader) == 0, "公开读路径不得触发推送"


    from django.core.management import call_command

    call_command("announcements_publish_due")
    assert _count(reader) == 1, "预告到点后定时命令没有把通知推出去"
    call_command("announcements_publish_due")
    assert _count(reader) == 1, "定时命令重复执行重复推送"


# --------------------------------------------------------------------------
# 4b. 收件人范围
# --------------------------------------------------------------------------


def test_推送只给活跃用户(api_client, staff_user, user_factory):
    from apps.accounts.services import ban_user, deactivate_account

    normal = user_factory(nickname="正常用户")
    banned = user_factory(nickname="封禁用户")
    gone = user_factory(nickname="注销用户")
    frozen = user_factory(nickname="被停用的号")
    ban_user(banned, reason="滥用")
    deactivate_account(gone)
    frozen.is_active = False
    frozen.save(update_fields=["is_active"])

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/announcements/", {"title": "全站广播", "body": "正文"}, format="json"
    )
    assert response.status_code == 201

    assert _count(normal) == 1
    for user, label in ((banned, "封禁"), (gone, "注销"), (frozen, "停用")):
        assert _count(user) == 0, f"{label}用户也收到了全站广播"

    from apps.homecontent.models import SiteAnnouncement

    row = SiteAnnouncement.objects.get(pk=response.json()["id"])
    assert row.notified_count == _count(normal) + _count(staff_user), (
        f"notified_count={row.notified_count} 与实际建出来的通知条数对不上"
    )


# --------------------------------------------------------------------------
# 4c. 停用后的可见性
# --------------------------------------------------------------------------


def test_停用后首页与历史页都不再出现(api_client, staff_user, announcement_factory):
    announcement_factory(title="要被停用的公告", body="正文")
    assert api_client.get("/api/v1/home/").json()["announcement"]["title"] == "要被停用的公告"

    from apps.homecontent.models import SiteAnnouncement

    row = SiteAnnouncement.objects.get(title="要被停用的公告")
    api_client.force_authenticate(staff_user)
    assert api_client.patch(
        f"/api/v1/home/admin/announcements/{row.pk}/", {"is_active": False}, format="json"
    ).status_code == 200

    api_client.force_authenticate(None)
    assert api_client.get("/api/v1/home/").json()["announcement"] is None
    listed = api_client.get("/api/v1/announcements/").json()["results"]
    assert all(a["title"] != "要被停用的公告" for a in listed)


def test_停用的公告连单条也问不出来(api_client, announcement_factory):
    """没有单条公开详情接口，所以停用后游客的唯一入口就是这两个列表 —— 都关着。"""
    from apps.homecontent.models import SiteAnnouncement

    row = announcement_factory(title="停用的", body="机密内容不该外泄")
    SiteAnnouncement.objects.filter(pk=row.pk).update(is_active=False)
    for url in ("/api/v1/home/", "/api/v1/announcements/", "/api/v1/announcements/?page=1"):
        assert "机密内容不该外泄" not in api_client.get(url).content.decode(), url


# --------------------------------------------------------------------------
# 4d. is_read 三态
# --------------------------------------------------------------------------


def test_is_read三态(api_client, staff_user, user_factory, announcement_factory):
    from apps.notifications import events
    from apps.notifications.models import Notification

    reader = user_factory(nickname="会读公告的人")
    announcement = announcement_factory(title="三态公告", body="正文")
    from apps.homecontent import services

    services.publish_announcement(announcement)

    # 游客：null
    assert api_client.get("/api/v1/home/").json()["announcement"]["is_read"] is None

    # 收到了但没读：False
    api_client.force_authenticate(reader)
    body = api_client.get("/api/v1/home/").json()["announcement"]
    assert body["is_read"] is False
    assert body["notification_id"] == Notification.objects.get(
        recipient=reader, event=events.SITE_ANNOUNCEMENT
    ).pk

    # 标已读之后：True
    from apps.notifications.services import mark_read

    mark_read(reader)
    assert api_client.get("/api/v1/home/").json()["announcement"]["is_read"] is True

    # 公告推送之后才注册的人：没有通知 → null，而不是 False
    api_client.force_authenticate(user_factory(nickname="后来的人"))
    assert api_client.get("/api/v1/home/").json()["announcement"]["is_read"] is None


def test_notification_id只会是自己的(api_client, user_factory, announcement_factory):
    """`notification_id` 是给前端标已读用的。拿到别人的 id 就等于能替别人标已读。"""
    from apps.notifications import events
    from apps.notifications.models import Notification

    a = user_factory(nickname="甲")
    b = user_factory(nickname="乙")
    announcement = announcement_factory(title="公告", body="正文")
    from apps.homecontent import services

    services.publish_announcement(announcement)

    api_client.force_authenticate(a)
    mine = api_client.get("/api/v1/home/").json()["announcement"]["notification_id"]
    assert (
        Notification.objects.get(pk=mine, event=events.SITE_ANNOUNCEMENT).recipient_id == a.pk
    )
    assert mine != Notification.objects.get(recipient=b, event=events.SITE_ANNOUNCEMENT).pk


# --------------------------------------------------------------------------
# 4e. 正文里的 HTML / 控制字符
# --------------------------------------------------------------------------

PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<img src=x onerror=alert(1)",  # 没有收尾的 `>`：正则 `<[^>]*>` 匹配不到
    "</textarea><svg onload=alert(1)>",
    "{{constructor.constructor('alert(1)')()}}",
    "&lt;script&gt;alert(1)&lt;/script&gt;",
]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_公告正文里的载荷要么被拒要么原样当数据(api_client, staff_user, payload):
    """纯文本字段的两种合格答案：400，或者原样存、原样吐（JSON 里就是一串字符）。

    不合格的第三种答案是「半转义」—— 存进去变成 `&lt;script&gt;`，
    那说明有人在写路径上做了 HTML 转义，读路径迟早会有人再 unescape 一次。
    """
    import json

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/announcements/", {"title": "载荷", "body": payload}, format="json"
    )
    if response.status_code == 400:
        return
    assert response.status_code == 201, response.content[:300]

    from apps.homecontent.models import SiteAnnouncement

    row = SiteAnnouncement.objects.get(pk=response.json()["id"])
    assert row.body == payload, f"正文被改写了：{row.body!r}"

    api_client.force_authenticate(None)
    listed = api_client.get("/api/v1/announcements/")
    assert listed["Content-Type"].startswith("application/json")
    assert json.loads(listed.content)["results"][0]["body"] == payload


def test_后台列表页把公告正文当文本渲染(user_factory):
    """后台的 list_display / search 结果是 HTML 页。正文里的标签必须是被转义的。"""
    from rest_framework.test import APIClient

    from apps.homecontent.models import SiteAnnouncement

    superuser = user_factory(nickname="后台管理员", email="admin-ann@example.com")
    superuser.is_staff = True
    superuser.is_superuser = True
    superuser.save(update_fields=["is_staff", "is_superuser"])
    client = APIClient()
    client.force_login(superuser)

    SiteAnnouncement.objects.create(
        title="<script>alert('title')</script>",
        body="<script>alert('body')</script>",
        published_at=timezone.now(),
    )
    for url in (
        f"{ADMIN}homecontent/siteannouncement/",
        f"{ADMIN}homecontent/siteannouncement/?q=script",
    ):
        page = client.get(url)
        assert page.status_code == 200
        assert b"<script>alert(" not in page.content, f"{url} 把公告正文当 HTML 渲染了"


# --------------------------------------------------------------------------
# 4f. 公开列表的参数不得打成 5xx
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["?page=0", "?page=-1", "?page=abc", "?page=99999999999999999999999",
     "?page_size=1000000", "?page_size=-1", "?page_size=abc", "?page=1&page_size=0"],
)
def test_公告列表的分页参数花样不得5xx(api_client, announcement_factory, query):
    announcement_factory(title="公告", body="正文")
    response = api_client.get(f"/api/v1/announcements/{query}")
    assert response.status_code < 500, f"{query} → {response.status_code}"
    if response.status_code == 200:
        assert len(response.json()["results"]) <= 100, "page_size 上限被绕过"


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------


def test_删公告后已推送的通知一并删除_API路径(api_client, staff_user, user_factory):
    reader = user_factory(nickname="收到公告的人A")
    api_client.force_authenticate(staff_user)
    created = api_client.post(
        "/api/v1/home/admin/announcements/",
        {"title": "要撤回的", "body": "正文", "is_active": True},
        format="json",
    )
    assert created.status_code == 201
    assert _count(reader) == 1

    other = api_client.post(
        "/api/v1/home/admin/announcements/",
        {"title": "留着的", "body": "正文", "is_active": True},
        format="json",
    )
    assert other.status_code == 201
    assert _count(reader) == 2

    deleted = api_client.delete(f"/api/v1/home/admin/announcements/{created.json()['id']}/")
    assert deleted.status_code == 204
    assert _count(reader) == 1, "删公告后通知没有一并撤回"

    api_client.force_authenticate(reader)
    rows = api_client.get("/api/v1/notifications/").json()["results"]
    blobs = [f"{n.get('title', '')} {n.get('payload', {})}" for n in rows]
    assert not any("要撤回的" in b for b in blobs), "撤回的公告仍留在通知里"
    assert any("留着的" in b for b in blobs), "撤回误伤了别的公告通知"


def test_删公告后已推送的通知一并删除_ORM与后台路径(api_client, staff_user, user_factory):
    """Django 后台删除走的是 ORM delete，信号同样要生效。"""
    from apps.homecontent.models import SiteAnnouncement

    reader = user_factory(nickname="收到公告的人B")
    api_client.force_authenticate(staff_user)
    created = api_client.post(
        "/api/v1/home/admin/announcements/",
        {"title": "后台删", "body": "正文", "is_active": True},
        format="json",
    )
    assert created.status_code == 201 and _count(reader) == 1
    SiteAnnouncement.objects.filter(pk=created.json()["id"]).delete()
    assert _count(reader) == 0
