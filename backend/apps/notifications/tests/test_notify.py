"""通知：建记录 + 按邮件偏好发信 + 接口只服务本人。"""

from __future__ import annotations

import pytest
from django.core import mail

from apps.notifications import events
from apps.notifications.models import EmailPreference, Notification
from apps.notifications.services import notify

pytestmark = pytest.mark.django_db


def test_事件清单包含13条业务事件与站长公告():

    assert len(events.ALL_EVENTS) == 14
    assert events.SITE_ANNOUNCEMENT in events.ALL_EVENTS
    assert set(events.EVENT_LABELS) == set(events.ALL_EVENTS)


def test_默认不发邮件只建站内记录(user_factory):
    user = user_factory(nickname="收通知的")
    notification = notify(user, events.REVIEW_OPENED, payload={"message": "去评价吧"})
    assert notification is not None
    assert Notification.objects.filter(recipient=user, event=events.REVIEW_OPENED).count() == 1
    assert len(mail.outbox) == 0
    assert EmailPreference.objects.get(user=user).email_enabled is False


def test_开启总开关后发邮件(user_factory):
    user = user_factory(nickname="要邮件的", email="want@example.com")
    preference = EmailPreference.objects.create(user=user, email_enabled=True)
    assert preference.wants(events.REVIEW_OPENED)

    notify(user, events.REVIEW_OPENED, payload={"message": "去评价吧"})
    assert len(mail.outbox) == 1
    assert "want@example.com" in mail.outbox[0].to


def test_按事件关闭时不发邮件(user_factory):
    user = user_factory(nickname="挑事件的", email="pick@example.com")
    EmailPreference.objects.create(
        user=user, email_enabled=True, per_event={events.REVIEW_OPENED: False}
    )
    notify(user, events.REVIEW_OPENED)
    assert len(mail.outbox) == 0
    notify(user, events.SIGNUP_RESULT)
    assert len(mail.outbox) == 1


def test_未知事件报错(user_factory):
    with pytest.raises(ValueError):
        notify(user_factory(nickname="乱发的"), "not_a_real_event")


def test_已注销用户不再收通知(user_factory):
    from apps.accounts.services import deactivate_account

    user = user_factory(nickname="注销的")
    deactivate_account(user)
    assert notify(user, events.REVIEW_OPENED) is None
    assert Notification.objects.filter(recipient=user).count() == 0


def test_通知列表只给本人(api_client, user_factory):
    me = user_factory(nickname="本人")
    other = user_factory(nickname="别人")
    notify(me, events.SIGNUP_RESULT)
    notify(other, events.SIGNUP_RESULT)

    api_client.force_authenticate(user=me)
    body = api_client.get("/api/v1/notifications/").json()
    assert body["count"] == 1
    assert body["results"][0]["event"] == events.SIGNUP_RESULT


def test_标已读与未读数(api_client, user_factory):
    me = user_factory(nickname="读通知的")
    notify(me, events.SIGNUP_RESULT)
    notify(me, events.REVIEW_OPENED)
    api_client.force_authenticate(user=me)

    assert api_client.get("/api/v1/notifications/unread-count/").json()["unread"] == 2
    response = api_client.post("/api/v1/notifications/read/", {}, format="json")
    assert response.json() == {"updated": 2, "unread": 0}


def test_不能标记他人的通知为已读(api_client, user_factory):
    me = user_factory(nickname="甲甲甲")
    other = user_factory(nickname="乙乙乙")
    foreign = notify(other, events.SIGNUP_RESULT)
    api_client.force_authenticate(user=me)
    response = api_client.post("/api/v1/notifications/read/", {"ids": [foreign.pk]}, format="json")
    assert response.json()["updated"] == 0
    foreign.refresh_from_db()
    assert foreign.read_at is None


def test_偏好读写(api_client, user_factory):
    me = user_factory(nickname="设置偏好的")
    api_client.force_authenticate(user=me)

    body = api_client.get("/api/v1/notifications/preference/").json()
    assert body["email_enabled"] is False
    assert len(body["available_events"]) == 14

    response = api_client.patch(
        "/api/v1/notifications/preference/",
        {"email_enabled": True, "per_event": {events.SIGNUP_RECEIVED: False}},
        format="json",
    )
    assert response.status_code == 200
    preference = EmailPreference.objects.get(user=me)
    assert preference.email_enabled is True
    assert preference.wants(events.SIGNUP_RECEIVED) is False


def test_偏好拒绝未知事件(api_client, user_factory):
    me = user_factory(nickname="乱填的")
    api_client.force_authenticate(user=me)
    response = api_client.patch(
        "/api/v1/notifications/preference/",
        {"per_event": {"nonsense_event": True}},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
