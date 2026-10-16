"""资源区后台：站主在这里审核投稿，并把上传/审核权限位授给用户或组。

授权方式（不需要改代码，对应 deferred 的「头衔机制」）：
后台 → 用户（或组）→ 权限 → 勾选「资源区 | 资源 | Can add 资源」＝上传权限位，
「资源区 | 资源 | 可以审核资源区投稿」＝审核权限位。
"""

from __future__ import annotations

from django.contrib import admin

from apps.resources.models import Resource
from apps.resources.services import can_moderate


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "category", "uploader", "is_approved", "created_at"]
    list_filter = ["is_approved", "kind", "category"]
    search_fields = ["title", "description", "url", "uploader__nickname"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["uploader"]
    actions = ["approve_selected", "unapprove_selected"]
    date_hierarchy = "created_at"

    def has_approve_permission(self, request) -> bool:
        """给下面两个动作用（Django 的 `@admin.action(permissions=[...])` 约定）。"""
        return can_moderate(request.user)

    @admin.action(description="通过审核（公开给所有人）", permissions=["approve"])
    def approve_selected(self, request, queryset) -> None:
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"已通过 {updated} 条资源")

    @admin.action(description="撤回审核（转为待审）", permissions=["approve"])
    def unapprove_selected(self, request, queryset) -> None:
        updated = queryset.update(is_approved=False)
        self.message_user(request, f"已撤回 {updated} 条资源")
