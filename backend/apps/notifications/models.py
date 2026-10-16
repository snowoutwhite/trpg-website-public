"""站内通知与邮件偏好。"""

from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.notifications import events
from common.models import TimeStampedModel


class Notification(models.Model):
    """一条站内通知。

    隐私约定：`actor` 只在「公开的行为」里填（例如谁报名了你的团）。
    匿名评价相关的通知一律不得写 actor，也不得在 payload 里放评价人线索。
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.CharField("事件", max_length=40, choices=events.EVENT_CHOICES)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acted_notifications",
        help_text="触发者；匿名场景必须留空",
    )

    target_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    target_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = GenericForeignKey("target_content_type", "target_object_id")

    payload = models.JSONField("附加数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    read_at = models.DateTimeField("已读时间", null=True, blank=True)

    class Meta:
        verbose_name = "通知"
        verbose_name_plural = "通知"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["recipient", "read_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.recipient_id}:{self.event}"

    @property
    def title(self) -> str:
        return events.EVENT_LABELS.get(self.event, self.event)


class EmailPreference(TimeStampedModel):
    """邮件提醒偏好：总开关默认关。

    `per_event` 是 {事件名: bool} 的覆盖表；总开关关闭时一律不发。
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_preference"
    )
    email_enabled = models.BooleanField("接收邮件提醒", default=False)
    per_event = models.JSONField("按事件覆盖", default=dict, blank=True)

    class Meta:
        verbose_name = "邮件偏好"
        verbose_name_plural = "邮件偏好"

    def __str__(self) -> str:
        return f"{self.user_id}:{'on' if self.email_enabled else 'off'}"

    def wants(self, event: str) -> bool:
        if not self.email_enabled:
            return False
        return bool(self.per_event.get(event, True))
