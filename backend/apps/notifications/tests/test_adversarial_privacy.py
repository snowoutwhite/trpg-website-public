"""对抗性测试 · 通知：能不能读别人的、标别人的已读、改别人的邮件偏好、邮件里带别人邮箱。"""

from __future__ import annotations

import pytest
from django.core import mail

from apps.notifications import events
from apps.notifications.models import EmailPreference, Notification
from apps.notifications.services import notify

pytestmark = pytest.mark.django_db

LIST = "/api/v1/notifications/"
UNREAD = "/api/v1/notifications/unread-count/"
READ = "/api/v1/notifications/read/"
PREFERENCE = "/api/v1/notifications/preference/"


def test_cannot_read_other_users_notifications(api_client, user_factory):
    victim = user_factory(nickname="受害者", email="victim@example.com")
    attacker = user_factory(nickname="攻击者", email="attacker@example.com")
    notify(victim, events.SIGNUP_RECEIVED, payload={"message": "受害者的私密内容XYZ"})

    api_client.force_authenticate(attacker)
    body = api_client.get(LIST).content.decode()
    assert "受害者的私密内容XYZ" not in body
    assert api_client.get(LIST).json()["count"] == 0
    assert api_client.get(UNREAD).json()["unread"] == 0


@pytest.mark.parametrize("param", ["?recipient=1", "?user=1", "?recipient_id=1", "?all=1"])
def test_query_params_cannot_widen_notification_scope(api_client, user_factory, param):
    victim = user_factory(nickname="受害者B", email="victim-b@example.com")
    attacker = user_factory(nickname="攻击者B", email="attacker-b@example.com")
    notify(victim, events.SIGNUP_RECEIVED, payload={"message": "别人的通知BBB"})

    api_client.force_authenticate(attacker)
    assert "别人的通知BBB" not in api_client.get(LIST + param).content.decode()


def test_cannot_mark_other_users_notifications_read(api_client, user_factory):
    victim = user_factory(nickname="受害者C", email="victim-c@example.com")
    attacker = user_factory(nickname="攻击者C", email="attacker-c@example.com")
    target = notify(victim, events.SIGNUP_RECEIVED)

    api_client.force_authenticate(attacker)
    response = api_client.post(READ, {"ids": [target.pk]}, format="json")
    assert response.status_code == 200
    assert response.json()["updated"] == 0

    target.refresh_from_db()
    assert target.read_at is None, "别人的通知被标成已读了"


def test_mark_all_read_does_not_touch_others(api_client, user_factory):
    victim = user_factory(nickname="受害者D", email="victim-d@example.com")
    attacker = user_factory(nickname="攻击者D", email="attacker-d@example.com")
    target = notify(victim, events.SIGNUP_RECEIVED)
    own = notify(attacker, events.SIGNUP_RECEIVED)

    api_client.force_authenticate(attacker)
    assert api_client.post(READ, {}, format="json").status_code == 200

    target.refresh_from_db()
    own.refresh_from_db()
    assert target.read_at is None
    assert own.read_at is not None


def test_mark_read_ids_are_bounded(api_client, user_factory):
    """ids 必须有上限，否则一次请求就能拼出超长 IN 查询压垮数据库。"""
    user = user_factory(nickname="刷已读", email="bulk@example.com")
    api_client.force_authenticate(user)
    response = api_client.post(READ, {"ids": list(range(1, 60000))}, format="json")
    assert response.status_code == 400, f"超长 ids 被接受：{response.status_code}"


def test_mark_read_rejects_garbage_ids(api_client, user_factory):
    user = user_factory(nickname="脏参数", email="dirty@example.com")
    api_client.force_authenticate(user)
    for bad in [{"ids": "1 OR 1=1"}, {"ids": [{"x": 1}]}, {"ids": ["' OR '1'='1"]}]:
        assert api_client.post(READ, bad, format="json").status_code == 400, bad


def test_cannot_change_other_users_email_preference(api_client, user_factory):
    victim = user_factory(nickname="受害者E", email="victim-e@example.com")
    attacker = user_factory(nickname="攻击者E", email="attacker-e@example.com")
    EmailPreference.objects.create(user=victim, email_enabled=False)

    api_client.force_authenticate(attacker)
    response = api_client.patch(
        PREFERENCE,
        {"email_enabled": True, "user": victim.pk, "id": victim.pk},
        format="json",
    )
    assert response.status_code == 200

    victim_preference = EmailPreference.objects.get(user=victim)
    assert victim_preference.email_enabled is False, "改到了别人的邮件偏好"
    assert EmailPreference.objects.get(user=attacker).email_enabled is True


def test_preference_rejects_unknown_events(api_client, user_factory):
    user = user_factory(nickname="乱填事件", email="pref@example.com")
    api_client.force_authenticate(user)
    response = api_client.patch(
        PREFERENCE, {"per_event": {"not_an_event": True}}, format="json"
    )
    assert response.status_code == 400


def test_notification_list_never_leaks_emails(api_client, user_factory):
    """通知里带上 actor 时，也只能是公开字段，绝不能带邮箱。"""
    actor = user_factory(nickname="报名者", email="signup-actor@example.com")
    recipient = user_factory(nickname="GM本人", email="gm@example.com")
    notify(recipient, events.SIGNUP_RECEIVED, actor=actor)

    api_client.force_authenticate(recipient)
    body = api_client.get(LIST).content.decode()
    assert "signup-actor@example.com" not in body
    assert "gm@example.com" not in body
    item = api_client.get(LIST).json()["results"][0]
    assert set(item["actor"]) == {"id", "nickname", "avatar", "is_gm"}


def test_email_not_sent_when_preference_is_off_by_default(user_factory):
    """邮件偏好默认关：只建站内记录，一封邮件都不许发。"""
    user = user_factory(nickname="默认关", email="default-off@example.com")
    mail.outbox.clear()

    notify(user, events.SIGNUP_RECEIVED, payload={"message": "有人报名"})

    assert Notification.objects.filter(recipient=user).count() == 1
    assert EmailPreference.objects.get(user=user).email_enabled is False
    assert mail.outbox == [], "偏好默认关，却发出了邮件"


def test_email_respects_per_event_override(user_factory):
    user = user_factory(nickname="按事件关", email="per-event@example.com")
    preference = EmailPreference.objects.create(user=user, email_enabled=True)
    preference.per_event = {events.SIGNUP_RECEIVED: False}
    preference.save()
    mail.outbox.clear()

    notify(user, events.SIGNUP_RECEIVED)
    assert mail.outbox == []

    notify(user, events.SIGNUP_RESULT)
    assert len(mail.outbox) == 1


def test_email_body_contains_no_third_party_address(user_factory):
    """通知邮件的收件人与正文里都不得出现除收件人以外的任何邮箱。"""
    actor = user_factory(nickname="他人F", email="third-party@example.com")
    recipient = user_factory(nickname="收件人F", email="recipient-f@example.com")
    EmailPreference.objects.create(user=recipient, email_enabled=True)
    mail.outbox.clear()

    notify(recipient, events.SIGNUP_RECEIVED, actor=actor, payload={"message": "有人报名了"})

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.recipients() == ["recipient-f@example.com"]
    assert message.cc == [] and message.bcc == []
    assert "third-party@example.com" not in message.body
    assert "third-party@example.com" not in message.subject


def test_notify_rejects_unknown_event(user_factory):
    user = user_factory(nickname="未知事件", email="unknown-event@example.com")
    with pytest.raises(ValueError):
        notify(user, "definitely_not_an_event")


def test_notify_skips_deactivated_recipient(user_factory):
    from apps.accounts.services import deactivate_account

    user = user_factory(nickname="注销收件", email="gone@example.com")
    deactivate_account(user)
    mail.outbox.clear()

    assert notify(user, events.SIGNUP_RECEIVED) is None
    assert Notification.objects.filter(recipient=user).count() == 0
    assert mail.outbox == []


def test_guest_cannot_touch_notifications(api_client):
    for method, path in [
        ("get", LIST),
        ("get", UNREAD),
        ("post", READ),
        ("get", PREFERENCE),
        ("patch", PREFERENCE),
    ]:
        response = getattr(api_client, method)(path, {}, format="json")
        assert response.status_code in (401, 403), f"{method} {path} → {response.status_code}"


def test_banned_user_cannot_read_notifications(api_client, user_factory):
    user = user_factory(nickname="被封读通知", email="banned-notify@example.com")
    user.is_banned = True
    user.is_active = False
    user.save(update_fields=["is_banned", "is_active"])
    api_client.force_authenticate(user)
    assert api_client.get(LIST).status_code == 403
