"""积分账本与称号。"""

from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db import models
from django.utils import timezone

from common.models import TimeStampedModel

# 积分变动原因
REASON_REPORT_SUBMITTED = "report_submitted"
REASON_REVOKED_BY_ADMIN = "revoked_by_admin"
REASON_MANUAL = "manual"
REASON_CHOICES = [
    (REASON_REPORT_SUBMITTED, "上传战报"),
    (REASON_REVOKED_BY_ADMIN, "站主撤销"),
    (REASON_MANUAL, "站主手工调整"),
]


class PointsLedger(TimeStampedModel):
    """一条积分流水。只增不改：撤销 = 追加一条负数行，不回头改/删原行。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="points_entries",
        verbose_name="用户",
    )
    amount = models.IntegerField("积分变动", help_text="正数为发放，负数为撤销或扣减")
    reason = models.CharField("原因", max_length=32, choices=REASON_CHOICES, db_index=True)

    # 关联对象（战报、团……）。用 GenericFK，避免积分 app 反向依赖任何业务 app。
    ref_content_type = models.ForeignKey(
        "contenttypes.ContentType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="关联对象类型",
    )
    ref_object_id = models.PositiveBigIntegerField("关联对象 ID", null=True, blank=True)
    ref = GenericForeignKey("ref_content_type", "ref_object_id")

    dedupe_key = models.CharField(
        "去重键",
        max_length=190,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "同一个去重键只会发一次积分。战报用「report:game:<团>:user:<人>」，"
            "所以删掉战报再写一份也不会二次发分；撤销之后同样不会复发。"
        ),
    )
    revokes = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="revocations",
        verbose_name="撤销的流水",
        help_text="本行是对该行的撤销（金额相反）",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="points_entries_created",
        verbose_name="操作人",
        help_text="站主手工发放/撤销时记录；系统自动发放为空",
    )
    note = models.CharField("备注", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "积分流水"
        verbose_name_plural = "积分流水"
        ordering = ["-created_at", "-id"]
        constraints = [
            # NULL 之间互不冲突，所以不带去重键的行可以有任意多条。
            models.UniqueConstraint(fields=["dedupe_key"], name="uniq_points_dedupe_key"),
            # 一条流水最多被撤销一次。
            models.UniqueConstraint(fields=["revokes"], name="uniq_points_revocation"),
        ]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.user.nickname} {self.amount:+d}（{self.get_reason_display()}）"

    @property
    def is_revoked(self) -> bool:
        return self.revocations.exists()


class Title(TimeStampedModel):
    """业务规则与安全约束。"""

    name = models.CharField("称号", max_length=30, unique=True)
    description = models.TextField("说明", blank=True, default="")
    cost = models.PositiveIntegerField("兑换所需积分", default=0)

    class Meta:
        verbose_name = "称号"
        verbose_name_plural = "称号"
        ordering = ["cost", "name"]

    def __str__(self) -> str:
        return self.name


class UserTitle(models.Model):
    """某人拥有的称号。首发只由站主在后台授予。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="titles",
        verbose_name="用户",
    )
    title = models.ForeignKey(
        Title, on_delete=models.CASCADE, related_name="holders", verbose_name="称号"
    )
    granted_at = models.DateTimeField("获得时间", default=timezone.now)

    class Meta:
        verbose_name = "用户称号"
        verbose_name_plural = "用户称号"
        ordering = ["-granted_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "title"], name="uniq_user_title")
        ]

    def __str__(self) -> str:
        return f"{self.user.nickname} · {self.title.name}"
