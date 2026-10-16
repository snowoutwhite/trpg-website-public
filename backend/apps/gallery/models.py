"""活动相册（gallery）：照片三档尺寸 + 举报/下架诉求。"""

from __future__ import annotations

import posixpath
import uuid

from django.conf import settings
from django.db import models

from common import images
from common.models import TimeStampedModel

# --------------------------------------------------------------------------

# --------------------------------------------------------------------------

# 相册 jpg/png/webp，10 MB/张，每团 50 张。
PHOTO_MAX_BYTES = 10 * 1024 * 1024
PHOTO_MAX_PER_GAME = 50
ALLOWED_EXTENSIONS = ("jpg", "jpeg", "png", "webp")


THUMBNAIL_MAX_SIDE = 400
PREVIEW_MAX_SIDE = 1600

# WebP 容器的硬上限（单一真源在 `common.images`，W5 起 `to_webp()` 自己也会封顶）。
# 「原图」档在调用侧也按这个值封顶：那一档本来就是转码产物，不是像素级原始文件。
# 用例 `test_extremely_wide_panorama_does_not_500`。
WEBP_MAX_SIDE = images.WEBP_MAX_SIDE

# 三档尺寸的对外名字（`?size=` 取值），顺带充当字段名映射表。
SIZE_THUMB = "thumb"
SIZE_PREVIEW = "preview"
SIZE_ORIGINAL = "original"
SIZE_FIELDS = {
    SIZE_THUMB: "thumbnail",
    SIZE_PREVIEW: "preview",
    SIZE_ORIGINAL: "original",
}

# --------------------------------------------------------------------------
# 状态机
# --------------------------------------------------------------------------

PHOTO_PENDING_REVIEW = "pending_review"
PHOTO_PUBLIC = "public"
PHOTO_TAKEN_DOWN = "taken_down"
PHOTO_REJECTED = "rejected"
PHOTO_STATUS_CHOICES = [
    (PHOTO_PENDING_REVIEW, "待审核"),
    (PHOTO_PUBLIC, "已公开"),
    (PHOTO_TAKEN_DOWN, "已下架"),
    (PHOTO_REJECTED, "已驳回"),
]

# 占每团 50 张配额的状态：驳回的照片不再是「相册里的照片」，不占配额，

QUOTA_STATUSES = (PHOTO_PENDING_REVIEW, PHOTO_PUBLIC, PHOTO_TAKEN_DOWN)

REPORT_OPEN = "open"
REPORT_HANDLED = "handled"
REPORT_STATUS_CHOICES = [
    (REPORT_OPEN, "待处理"),
    (REPORT_HANDLED, "已处理"),
]

# 举报理由枚举（自由文本放 reason_text）
REASON_IN_PHOTO = "in_photo"
REASON_INAPPROPRIATE = "inappropriate"
REASON_OTHER = "other"
REASON_CHOICES = [
    (REASON_IN_PHOTO, "我在照片里，要求下架"),
    (REASON_INAPPROPRIATE, "不当内容"),
    (REASON_OTHER, "其他"),
]

# 站主处理举报的三种结果
RESULT_PENDING = ""
RESULT_RESTORED = "restored"
RESULT_TAKEN_DOWN = "taken_down"
RESULT_DISMISSED = "dismissed"
RESULT_CHOICES = [
    (RESULT_PENDING, "未处理"),
    (RESULT_RESTORED, "恢复展示"),
    (RESULT_TAKEN_DOWN, "确认下架"),
    (RESULT_DISMISSED, "不予处理"),
]


PERM_MODERATE = "gallery.moderate_photo"


def photo_upload_to(instance, filename: str) -> str:
    """受保护目录 + uuid 文件名。

    **用户的原始文件名一个字符都不进路径**：这里只认服务端自己传进来的档位名
    （original / preview / thumb），认不出就叫 img；后缀恒为 .webp（三档都重编码过）。
    路径穿越、双扩展名、控制字符这类文件名攻击在这一步就整段被丢掉。
    """
    stem = posixpath.splitext(posixpath.basename(filename or ""))[0]
    tier = stem if stem in ("original", "preview", "thumb") else "img"
    return posixpath.join(
        settings.PROTECTED_MEDIA_DIRNAME,
        "gallery",
        f"{uuid.uuid4().hex}-{tier}.webp",
    )


class Photo(TimeStampedModel):
    """一张活动照片。三档都由服务端重新编码为 WebP，不保留用户上传的原始字节。"""

    game = models.ForeignKey(
        "games.Game",
        on_delete=models.CASCADE,
        related_name="photos",
        verbose_name="团",
    )
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="uploaded_photos",
        verbose_name="上传者",
        help_text="只能是该团的 GM",
    )

    original = models.ImageField("原图", upload_to=photo_upload_to, max_length=255)
    preview = models.ImageField("预览图", upload_to=photo_upload_to, max_length=255)
    thumbnail = models.ImageField("缩略图", upload_to=photo_upload_to, max_length=255)

    width = models.PositiveIntegerField("原图宽", default=0)
    height = models.PositiveIntegerField("原图高", default=0)
    size = models.PositiveIntegerField("原图字节数", default=0)

    status = models.CharField(
        "状态",
        max_length=20,
        choices=PHOTO_STATUS_CHOICES,
        default=PHOTO_PUBLIC,
        db_index=True,
    )
    caption = models.CharField("图注", max_length=200, blank=True, default="")
    taken_down_reason = models.TextField(
        "下架/驳回理由", blank=True, default="", help_text="站主下架或驳回时填写，举报后自动下架时记录举报理由"
    )
    is_featured = models.BooleanField(
        "首页精选",
        default=False,
        db_index=True,
        help_text="站主勾选，进首页照片墙；**只有已公开的照片能勾**，照片一旦离开公开状态自动取消",
    )

    class Meta:
        verbose_name = "活动照片"
        verbose_name_plural = "活动相册"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["game", "status"]),
            models.Index(fields=["uploader", "status"]),
            models.Index(fields=["is_featured", "status", "-created_at"]),
        ]
        permissions = [("moderate_photo", "可以审核相册照片与处理举报")]
        constraints = [
            # 数据库层兜底：精选 ⇒ 已公开。服务层（`homecontent.services.set_photo_featured`
            # 与本 app 的 `_unfeature`）已经守着，但后台批量改、数据迁移、将来某个
            # 忘了走 service 的新路径都可能把一张待审/已下架的照片推上首页 ——
            # 那是拿「被拍到者已经提出的下架诉求」去换首页版面，必须在最底层堵死。
            models.CheckConstraint(
                condition=models.Q(is_featured=False) | models.Q(status=PHOTO_PUBLIC),
                name="featured_photo_must_be_public",
            )
        ]

    def __str__(self) -> str:
        return f"{self.game_id}#{self.pk}"

    @property
    def is_visible_to_everyone(self) -> bool:
        """是否对「任意登录用户」可见（相册整体仍需登录）。"""
        return self.status == PHOTO_PUBLIC

    def file_for(self, size: str):
        """按 `?size=` 取对应的 FileField；未知档位返回 None。"""
        field_name = SIZE_FIELDS.get(size)
        if field_name is None:
            return None
        return getattr(self, field_name, None)

    def stored_files(self) -> list:
        return [f for f in (self.original, self.preview, self.thumbnail) if f]


class PhotoReport(TimeStampedModel):
    """举报 / 下架诉求。"""

    photo = models.ForeignKey(
        Photo, on_delete=models.CASCADE, related_name="reports", verbose_name="照片"
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="photo_reports",
        verbose_name="举报人",
        help_text="「相册需登录」→ 不收匿名游客举报",
    )
    reason = models.CharField("理由", max_length=20, choices=REASON_CHOICES)
    reason_text = models.TextField("补充说明", blank=True, default="")

    status = models.CharField(
        "处理状态", max_length=16, choices=REPORT_STATUS_CHOICES, default=REPORT_OPEN, db_index=True
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_photo_reports",
        verbose_name="处理人",
    )
    handled_at = models.DateTimeField("处理时间", null=True, blank=True)
    result = models.CharField(
        "处理结果", max_length=20, choices=RESULT_CHOICES, blank=True, default=RESULT_PENDING
    )
    result_note = models.TextField("给举报人的说明", blank=True, default="")

    class Meta:
        verbose_name = "照片举报"
        verbose_name_plural = "照片举报"
        ordering = ["-created_at", "-id"]
        constraints = [
            # 防刷：同一个人对同一张照片**同时**只能有一条未处理的举报。
            # 历史举报处理后允许重新举报，唯一性仅约束待处理状态。
            # 条件唯一约束在 SQLite 与 PostgreSQL 上都支持。
            models.UniqueConstraint(
                fields=["photo", "reporter"],
                condition=models.Q(status=REPORT_OPEN),
                name="uniq_open_report_per_photo_user",
            )
        ]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self) -> str:
        return f"report#{self.pk} -> photo#{self.photo_id}"
