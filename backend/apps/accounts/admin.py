"""账号域后台。站主的管理动作都在这里，不开放为 API。"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import (
    AdminPasswordChangeForm,
    BaseUserCreationForm,
    ReadOnlyPasswordHashField,
)

from apps.accounts.models import GMApplication, InviteCode, NicknameHistory, User
from apps.accounts.services import (
    ban_user,
    mute_user,
    review_gm_application,
    unban_user,
    unmute_user,
)


class UserCreationAdminForm(BaseUserCreationForm):
    """后台新建用户：本站没有 username，用邮箱 + 昵称。"""

    class Meta:
        model = User
        fields = ("email", "nickname")
        field_classes: dict = {}


class UserChangeAdminForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField(
        label="密码", help_text="密码以哈希存储，无法查看；可用上方链接修改。"
    )

    class Meta:
        model = User
        fields = "__all__"
        field_classes: dict = {}


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserChangeAdminForm
    add_form = UserCreationAdminForm
    change_password_form = AdminPasswordChangeForm
    ordering = ["-date_joined"]
    list_display = ["nickname", "email", "is_gm", "is_banned", "is_muted", "is_deactivated", "date_joined"]
    list_filter = ["is_gm", "is_banned", "is_muted", "is_deactivated", "is_staff", "is_superuser"]
    search_fields = ["nickname", "email"]
    readonly_fields = ["date_joined", "last_login", "nickname_changed_at", "anonymized_email_hash", "deactivated_at"]
    filter_horizontal = ["groups", "user_permissions"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("资料", {"fields": ("nickname", "avatar", "nickname_changed_at")}),
        ("站内身份", {"fields": ("is_gm",)}),
        ("处置", {"fields": ("is_banned", "ban_reason", "is_muted", "mute_reason")}),
        ("注销", {"fields": ("is_deactivated", "deactivated_at", "anonymized_email_hash")}),
        ("权限", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("时间", {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "nickname", "password1", "password2")}),
    )
    actions = ["action_ban", "action_unban", "action_mute", "action_unmute"]

    @admin.action(description="封禁所选账号（禁止登录）")
    def action_ban(self, request, queryset) -> None:
        for user in queryset:
            ban_user(user, reason="后台批量封禁")
        self.message_user(request, f"已封禁 {queryset.count()} 个账号", messages.SUCCESS)

    @admin.action(description="解除封禁")
    def action_unban(self, request, queryset) -> None:
        for user in queryset:
            unban_user(user)
        self.message_user(request, f"已解封 {queryset.count()} 个账号", messages.SUCCESS)

    @admin.action(description="禁言所选账号（禁止放团/报名/评价）")
    def action_mute(self, request, queryset) -> None:
        for user in queryset:
            mute_user(user, reason="后台批量禁言")
        self.message_user(request, f"已禁言 {queryset.count()} 个账号", messages.SUCCESS)

    @admin.action(description="解除禁言")
    def action_unmute(self, request, queryset) -> None:
        for user in queryset:
            unmute_user(user)
        self.message_user(request, f"已解除禁言 {queryset.count()} 个账号", messages.SUCCESS)


@admin.register(NicknameHistory)
class NicknameHistoryAdmin(admin.ModelAdmin):
    list_display = ["user", "old_nickname", "new_nickname", "changed_at"]
    search_fields = ["old_nickname", "new_nickname"]
    readonly_fields = ["user", "old_nickname", "new_nickname", "changed_at"]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(InviteCode)
class InviteCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "max_uses", "used_count", "expires_at", "is_active", "created_by", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["code", "note"]
    readonly_fields = ["used_count", "created_at", "updated_at"]

    def save_model(self, request, obj, form, change) -> None:
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(GMApplication)
class GMApplicationAdmin(admin.ModelAdmin):
    list_display = ["applicant", "status", "created_at", "reviewed_at", "reviewer"]
    list_filter = ["status"]
    search_fields = ["applicant__nickname"]
    readonly_fields = ["applicant", "reason", "created_at", "reviewed_at", "reviewer"]
    actions = ["action_approve", "action_reject"]

    def has_add_permission(self, request) -> bool:
        return False

    @admin.action(description="通过所选 GM 申请")
    def action_approve(self, request, queryset) -> None:
        count = 0
        for application in queryset.filter(status=GMApplication.STATUS_PENDING):
            review_gm_application(application, approved=True, reviewer=request.user)
            count += 1
        self.message_user(request, f"已通过 {count} 份申请", messages.SUCCESS)

    @admin.action(description="驳回所选 GM 申请")
    def action_reject(self, request, queryset) -> None:
        count = 0
        for application in queryset.filter(status=GMApplication.STATUS_PENDING):
            review_gm_application(application, approved=False, reviewer=request.user)
            count += 1
        self.message_user(request, f"已驳回 {count} 份申请", messages.SUCCESS)
