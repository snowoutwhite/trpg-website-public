"""通知发送入口。

全站唯一的发通知方式是 `notify()`；业务代码不要自己 create Notification，
也不要自己 send_mail，否则邮件偏好会被绕过。
"""

from __future__ import annotations

import logging

from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone

from apps.notifications import events
from apps.notifications.models import EmailPreference, Notification

logger = logging.getLogger(__name__)


def get_email_preference(user) -> EmailPreference:
    preference, _ = EmailPreference.objects.get_or_create(user=user)
    return preference


def notify(
    recipient,
    event: str,
    *,
    actor=None,
    target: models.Model | None = None,
    payload: dict | None = None,
    send_email: bool | None = None,
) -> Notification | None:
    """创建一条站内通知，并按用户偏好决定是否同时发邮件。

    - `recipient` 已注销或被封禁时直接跳过。
    - `send_email=None` 表示按偏好判断；传 True/False 可强制覆盖（极少用）。
    """
    if recipient is None or not getattr(recipient, "pk", None):
        return None
    if getattr(recipient, "is_deactivated", False):
        return None
    if event not in events.EVENT_LABELS:
        raise ValueError(f"未知的通知事件：{event}")

    notification = Notification(
        recipient=recipient,
        event=event,
        actor=actor,
        payload=payload or {},
    )
    if target is not None:
        notification.target_content_type = ContentType.objects.get_for_model(target)
        notification.target_object_id = target.pk
    notification.save()

    if send_email is None:
        send_email = get_email_preference(recipient).wants(event)
    if send_email:
        _send_email(notification)
    return notification


#: 广播时一次写库多少条。太大在 SQLite 上会撞绑定变量上限，太小是白白多跑几趟。
BROADCAST_CHUNK_SIZE = 500


def notify_many(
    recipients,
    event: str,
    *,
    actor=None,
    target: models.Model | None = None,
    payload: dict | None = None,
) -> int:
    """给一批人各建一条同样的通知，返回实际建了多少条。

    存在的理由是站长公告这种**全站广播**：逐个 `notify()` 会打出 N 次 INSERT
    加 N 次偏好查询，站点稍微大一点就是一次请求里几千趟数据库往返。
    这里分块 `bulk_create`，邮件仍然逐人按 `EmailPreference` 判断 ——
    所以业务代码依然不需要（也不许）自己 `send_mail`。

    跳过的人与 `notify()` 一致：已注销的号不收。
    """
    if event not in events.EVENT_LABELS:
        raise ValueError(f"未知的通知事件：{event}")

    content_type = None
    target_id = None
    if target is not None:
        content_type = ContentType.objects.get_for_model(target)
        target_id = target.pk

    queryset = recipients
    if hasattr(queryset, "filter"):
        queryset = queryset.filter(is_deactivated=False)
        iterator = queryset.iterator(chunk_size=BROADCAST_CHUNK_SIZE)
    else:
        iterator = (u for u in queryset if not getattr(u, "is_deactivated", False))

    created_total = 0
    chunk: list[Notification] = []
    users: list = []

    def flush() -> None:
        nonlocal created_total, chunk, users
        if not chunk:
            return
        Notification.objects.bulk_create(chunk)
        created_total += len(chunk)
        # 偏好一次取一整块，不逐人 `get_or_create`（那正是我们想省掉的 N 次往返）。
        # **没有偏好行的人一律当「不发」**：总开关默认就是关的（需求 4），
        # 为了一次广播给全站每个人凭空插一行偏好，代价与收益都不对。
        wanted = {
            preference.user_id: preference.wants(event)
            for preference in EmailPreference.objects.filter(
                user_id__in=[u.pk for u in users]
            ).only("user_id", "email_enabled", "per_event")
        }
        for user, notification in zip(users, chunk, strict=True):
            notification.recipient = user  # bulk_create 不会回填关联对象
            if wanted.get(user.pk, False):
                _send_email(notification)
        chunk = []
        users = []

    for user in iterator:
        if user is None or not getattr(user, "pk", None):
            continue
        chunk.append(
            Notification(
                recipient_id=user.pk,
                event=event,
                actor=actor,
                target_content_type=content_type,
                target_object_id=target_id,
                payload=payload or {},
            )
        )
        users.append(user)
        if len(chunk) >= BROADCAST_CHUNK_SIZE:
            flush()
    flush()
    return created_total


def _send_email(notification: Notification) -> None:
    recipient_email = getattr(notification.recipient, "email", None)
    if not recipient_email:
        return

    from apps.siteconfig.services import get_config

    config = get_config()
    title = events.EVENT_LABELS.get(notification.event, notification.event)
    subject = f"[{config.site_name}] {title}"
    body_lines = [f"{notification.recipient.nickname}，你好：", "", title]
    message = notification.payload.get("message")
    if message:
        body_lines += ["", str(message)]
    body_lines += ["", f"—— {config.site_name}"]

    try:
        send_mail(
            subject=subject,
            message="\n".join(body_lines),
            from_email=None,  # 用 DEFAULT_FROM_EMAIL
            recipient_list=[recipient_email],
            fail_silently=False,
        )
    except Exception:  # pragma: no cover - 邮件挂了不能拖垮业务流程
        logger.warning("通知邮件发送失败 event=%s", notification.event, exc_info=True)


def mark_read(user, notification_ids: list[int] | None = None) -> int:
    """把当前用户的通知标为已读；不传 id 表示全部。返回受影响条数。"""
    queryset = Notification.objects.filter(recipient=user, read_at__isnull=True)
    if notification_ids is not None:
        queryset = queryset.filter(pk__in=notification_ids)
    return queryset.update(read_at=timezone.now())


def unread_count(user) -> int:
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
