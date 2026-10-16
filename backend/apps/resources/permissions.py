"""资源区权限类。

**不判断 `is_superuser`**：一律问 Django 权限位，站主可以在后台把权限位授给某个用户或某个组
（将来的「头衔」），无需改代码。超级管理员的 `has_perm()` 恒为真，所以站主自动满足。
"""

from __future__ import annotations

from rest_framework import permissions

from apps.resources import services
from common.permissions import IsAuthenticatedAndActive, deny_like


class CanUploadResource(IsAuthenticatedAndActive):
    """POST 上传：需要 `resources.add_resource` 权限位。"""

    message = "没有资源上传权限，请联系站主开通"

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return services.can_upload(request.user)


class CanApproveResource(IsAuthenticatedAndActive):
    """审核：需要 `resources.approve_resource` 权限位。"""

    message = "没有资源审核权限"

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return services.can_moderate(request.user)


class ReadOnlyOrCanUpload(permissions.BasePermission):
    """列表接口：GET 谁都能读（内容由 queryset 过滤），POST 需要上传权限位。"""

    message = CanUploadResource.message

    def has_permission(self, request, view) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        inner = CanUploadResource()
        if inner.has_permission(request, view):
            return True
        # 封禁 / 注销号要拿到 account_banned / account_deactivated 而不是通用码（缺陷 D4）
        return deny_like(self, inner)


class ReadOnlyOrIsUploaderOrApprover(permissions.BasePermission):
    """详情接口：GET 谁都能读（未审核的已被 queryset 挡掉），
    PATCH/DELETE 仅上传者本人或有审核权限者。"""

    message = "只有上传者本人或有审核权限的人可以修改这条资源"

    def has_permission(self, request, view) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        # 账号状态的判定只有一处口径（含 account_banned / account_deactivated 两个 code）
        inner = IsAuthenticatedAndActive()
        if inner.has_permission(request, view):
            return True
        return deny_like(self, inner)

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return services.can_edit(request.user, obj)
