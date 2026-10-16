"""资源区（需求整理第 3 节）。"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models

from common.models import TimeStampedModel

#: 外链只允许 http/https，挡掉 javascript:、data:、file:、ftp: 等。
http_url_validator = URLValidator(schemes=["http", "https"], message="外链必须是 http 或 https 地址")


def resource_upload_to(instance: Resource, filename: str) -> str:
    """资源文件一律放受保护目录，文件名随机化。"""
    suffix = Path(filename).suffix.lower()[:16]
    return f"{settings.PROTECTED_MEDIA_DIRNAME}/resources/{uuid.uuid4().hex}{suffix}"


class ResourceKind(models.TextChoices):
    FILE = "file", "文件"
    LINK = "link", "链接"


class ResourceQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(is_approved=True)


class Resource(TimeStampedModel):
    """资源区条目：一个上传的文件，或一条站外链接。"""

    title = models.CharField("标题", max_length=120)
    description = models.TextField("说明", blank=True, default="")
    kind = models.CharField("类型", max_length=8, choices=ResourceKind.choices, default=ResourceKind.FILE)
    file = models.FileField(
        "文件",
        upload_to=resource_upload_to,
        blank=True,
        null=True,
        help_text="kind=file 时必填。不设大小上限，但可执行/脚本类扩展名会被拒绝。",
    )
    url = models.URLField(
        "外链",
        max_length=500,
        blank=True,
        default="",
        validators=[http_url_validator],
        help_text="kind=link 时必填，只接受 http/https。",
    )
    category = models.CharField("分类", max_length=40, blank=True, default="", db_index=True)
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="上传者",
        related_name="uploaded_resources",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="上传者注销后置空，条目本身保留",
    )
    is_approved = models.BooleanField(
        "已审核",
        default=False,
        db_index=True,
        help_text="未审核的条目只有上传者本人与有审核权限的人能看到",
    )

    objects = ResourceQuerySet.as_manager()

    class Meta:
        verbose_name = "资源"
        verbose_name_plural = "资源区"
        ordering = ["-created_at", "-id"]
        permissions = [("approve_resource", "可以审核资源区投稿")]

    def __str__(self) -> str:
        return self.title

    @property
    def is_file(self) -> bool:
        return self.kind == ResourceKind.FILE

    def clean(self) -> None:
        """kind 与 file/url 必须自洽。后台手工录入也要走这一关。"""
        super().clean()
        if self.kind == ResourceKind.FILE:
            if not self.file:
                raise ValidationError({"file": "文件类资源必须上传文件"})
            if self.url:
                raise ValidationError({"url": "文件类资源不应填外链"})
        else:
            if not self.url:
                raise ValidationError({"url": "链接类资源必须填外链"})
            if self.file:
                raise ValidationError({"file": "链接类资源不应上传文件"})
