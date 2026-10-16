"""战报：每人每团一份的 Markdown 记录 + 附件 + 举报。"""

from __future__ import annotations

import posixpath
import uuid

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel

VISIBILITY_PUBLIC = "public"
VISIBILITY_SAME_GAME = "same_game"
VISIBILITY_CHOICES = [
    (VISIBILITY_PUBLIC, "公开"),
    (VISIBILITY_SAME_GAME, "仅同团可见"),
]


BODY_MAX_LENGTH = 50_000


MAX_ATTACHMENTS = 10


def report_attachment_upload_to(instance: ReportAttachment, filename: str) -> str:
    """受保护目录 + uuid 文件名：路径不可猜，原始文件名只存字段里。"""
    extension = posixpath.splitext(filename)[1].lower()
    return posixpath.join(
        settings.PROTECTED_MEDIA_DIRNAME,
        "reports",
        f"{uuid.uuid4().hex}{extension}",
    )


class Report(TimeStampedModel):
    """一份战报 = 某人为某个团写的记录。"""

    game = models.ForeignKey(
        "games.Game", on_delete=models.CASCADE, related_name="reports", verbose_name="团"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="game_reports",
        verbose_name="作者",
    )
    title = models.CharField("标题", max_length=80)
    body_markdown = models.TextField(
        "正文（Markdown）",
        blank=True,
        default="",
        help_text="按原文存储，服务端不渲染；前端渲染前必须 sanitize",
    )
    visibility = models.CharField(
        "可见范围",
        max_length=16,
        choices=VISIBILITY_CHOICES,
        default=VISIBILITY_PUBLIC,
        db_index=True,
    )
    is_featured = models.BooleanField(
        "精选",
        default=False,
        db_index=True,
        help_text="站主在后台勾选；游客只能看到「精选 + 公开」的战报",
    )

    class Meta:
        verbose_name = "战报"
        verbose_name_plural = "战报"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["game", "author"], name="uniq_report_per_game_author")
        ]
        indexes = [
            models.Index(fields=["game", "-created_at"]),
            models.Index(fields=["is_featured", "visibility", "-created_at"]),
        ]
        permissions = [
            ("moderate_report", "可精选战报、删除他人战报、处理战报举报"),
        ]

    def __str__(self) -> str:
        return f"{self.title}（{self.author.nickname}）"

    @property
    def is_public(self) -> bool:
        return self.visibility == VISIBILITY_PUBLIC

    @property
    def visible_to_guests(self) -> bool:
        """业务规则与安全约束。"""
        return self.is_featured and self.is_public


class ReportAttachment(TimeStampedModel):
    """战报附件。白名单与大小与角色卡同一套。"""

    report = models.ForeignKey(
        Report, on_delete=models.CASCADE, related_name="attachments", verbose_name="战报"
    )
    file = models.FileField("文件", upload_to=report_attachment_upload_to, max_length=255)
    original_name = models.CharField("原始文件名", max_length=255)
    size = models.PositiveIntegerField("字节数", default=0)
    mime = models.CharField("MIME 类型", max_length=100, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_report_attachments",
        verbose_name="上传者",
    )

    class Meta:
        verbose_name = "战报附件"
        verbose_name_plural = "战报附件"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.report.title} · {self.original_name}"


# 举报处理状态
ABUSE_PENDING = "pending"
ABUSE_RESOLVED = "resolved"
ABUSE_DISMISSED = "dismissed"
ABUSE_STATUS_CHOICES = [
    (ABUSE_PENDING, "待处理"),
    (ABUSE_RESOLVED, "已处理"),
    (ABUSE_DISMISSED, "已驳回"),
]


class ReportReport(models.Model):
    """对一份战报的举报。

    命名说明：模型名里两个 report 分别是「战报」和「举报」，中文名是「战报举报」。
    `(report, reporter)` 唯一，一个人对同一份战报只能举报一次（防刷）。
    """

    report = models.ForeignKey(
        Report, on_delete=models.CASCADE, related_name="abuse_reports", verbose_name="被举报的战报"
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="report_abuse_reports",
        verbose_name="举报人",
    )
    reason = models.TextField("举报理由", max_length=1000)
    status = models.CharField(
        "处理状态", max_length=16, choices=ABUSE_STATUS_CHOICES, default=ABUSE_PENDING, db_index=True
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_report_abuse_reports",
        verbose_name="处理人",
    )
    handled_at = models.DateTimeField("处理时间", null=True, blank=True)
    handle_note = models.TextField("处理备注", blank=True, default="")
    created_at = models.DateTimeField("举报时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "战报举报"
        verbose_name_plural = "战报举报"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["report", "reporter"], name="uniq_report_abuse_once")
        ]

    def __str__(self) -> str:
        return f"举报 #{self.report_id}（{self.get_status_display()}）"
