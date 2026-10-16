"""账号域模型：User / NicknameHistory / InviteCode / GMApplication。"""

from __future__ import annotations

import secrets
import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.accounts.managers import UserManager
from common.models import TimeStampedModel

NICKNAME_MAX_LENGTH = 24
ANONYMIZED_NICKNAME_PREFIX = "已注销用户"


def avatar_upload_to(instance: User, filename: str) -> str:
    """头像是公开资源，直接放公开 media 目录；文件名随机化避免枚举。"""
    return f"avatars/{uuid.uuid4().hex}.webp"


class User(AbstractBaseUser, PermissionsMixin):
    """站内账号。

    - `email` 允许为空，仅用于注销后的匿名化（唯一约束下多个 NULL 不冲突）。
    - `is_active=False` 表示禁止登录（注销或封禁），`is_banned` 用来区分原因。
    """

    email = models.EmailField("邮箱", max_length=254, unique=True, null=True, blank=True)
    nickname = models.CharField("昵称", max_length=NICKNAME_MAX_LENGTH, unique=True)
    avatar = models.ImageField("头像", upload_to=avatar_upload_to, blank=True, null=True)

    is_gm = models.BooleanField("GM 身份", default=False)
    is_banned = models.BooleanField("已封禁", default=False, help_text="封禁后禁止登录")
    is_muted = models.BooleanField("已禁言", default=False, help_text="禁言后禁止放团/报名/评价")
    ban_reason = models.TextField("封禁理由", blank=True, default="")
    mute_reason = models.TextField("禁言理由", blank=True, default="")

    nickname_changed_at = models.DateTimeField("上次改昵称时间", null=True, blank=True)

    is_deactivated = models.BooleanField("已注销", default=False)
    deactivated_at = models.DateTimeField("注销时间", null=True, blank=True)
    anonymized_email_hash = models.CharField(
        "注销前邮箱哈希", max_length=64, blank=True, default="",
        help_text="注销时把邮箱做单向哈希留痕，用于申诉核对；不可逆",
    )

    is_staff = models.BooleanField("可登录后台", default=False)
    is_active = models.BooleanField("账号可用", default=True)
    date_joined = models.DateTimeField("注册时间", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nickname"]

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"
        ordering = ["-date_joined"]

    def __str__(self) -> str:
        return self.nickname

    @property
    def can_act(self) -> bool:
        """能否执行放团/报名/评价这类写操作。"""
        return self.is_active and not self.is_banned and not self.is_muted


class NicknameHistory(models.Model):
    """昵称变更留痕。"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="nickname_history")
    old_nickname = models.CharField("原昵称", max_length=NICKNAME_MAX_LENGTH)
    new_nickname = models.CharField("新昵称", max_length=NICKNAME_MAX_LENGTH)
    changed_at = models.DateTimeField("变更时间", auto_now_add=True)

    class Meta:
        verbose_name = "昵称变更记录"
        verbose_name_plural = "昵称变更记录"
        ordering = ["-changed_at"]

    def __str__(self) -> str:
        return f"{self.old_nickname} → {self.new_nickname}"


def generate_invite_code() -> str:
    return secrets.token_urlsafe(9)[:12].upper()


class InviteCode(TimeStampedModel):
    """站主生成的注册邀请码，可设最大使用次数与有效期。"""

    code = models.CharField("邀请码", max_length=32, unique=True, default=generate_invite_code)
    max_uses = models.PositiveIntegerField("最大使用次数", default=1)
    used_count = models.PositiveIntegerField("已用次数", default=0)
    expires_at = models.DateTimeField("有效期至", null=True, blank=True, help_text="留空表示不过期")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_invite_codes"
    )
    is_active = models.BooleanField("启用", default=True)
    note = models.CharField("备注", max_length=100, blank=True, default="")

    class Meta:
        verbose_name = "邀请码"
        verbose_name_plural = "邀请码"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.code

    def is_available(self, *, now=None) -> bool:
        now = now or timezone.now()
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at <= now:
            return False
        return self.used_count < self.max_uses


class GMApplication(TimeStampedModel):
    """GM 申请：只需写理由，由站主审批。"""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待审核"),
        (STATUS_APPROVED, "已通过"),
        (STATUS_REJECTED, "已驳回"),
    ]

    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name="gm_applications")
    reason = models.TextField("申请理由")
    status = models.CharField("状态", max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewer = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_gm_applications"
    )
    reviewed_at = models.DateTimeField("审批时间", null=True, blank=True)
    review_note = models.TextField("审批备注", blank=True, default="")

    class Meta:
        verbose_name = "GM 申请"
        verbose_name_plural = "GM 申请"
        ordering = ["-created_at"]
        constraints = [
            # 同一人同时只能有一份待审申请
            models.UniqueConstraint(
                fields=["applicant"],
                condition=models.Q(status="pending"),
                name="uniq_pending_gm_application_per_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.applicant.nickname} - {self.get_status_display()}"
