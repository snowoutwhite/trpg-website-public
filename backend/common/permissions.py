"""全站共用权限类。

拒绝理由要带**机器可读的 code**（缺陷 D4）：DRF 的 `APIView.check_permissions` 会把
权限实例上的 `message` 与 `code` 一起交给 `permission_denied()`，最终落进
`common.exceptions.api_exception_handler` 拼出的错误信封的 `error.code`。
不设 `code` 就一律是通用的 `permission_denied`，前端认不出「禁言」和「封禁」。

`code` / `message` 在 `has_permission()` 里按具体原因**写到实例上**（DRF 每个请求
都新建一次权限实例，见 `APIView.get_permissions()`，不会串到别的请求）。
"""

from rest_framework import permissions

# `common.exceptions` 的导入必须**留在函数体里**：本模块现在是 DRF 的
# `DEFAULT_PERMISSION_CLASSES`，settings 解析它的时机早于 `rest_framework.views`
# 装载完成，而 `common.exceptions` 正好要 import `rest_framework.views` ——
# 放在模块顶层会成环（ImportError: cannot import name 'AccountBanned' from
# partially initialized module 'common.exceptions'）。


def is_account_blocked(user) -> bool:
    """账号被封禁或停用（注销）—— 「登录了但这个账号不能用」的统一判定。

    存在的理由：认证后端现在会把封禁 / 停用账号**取回来**
    （`apps.accounts.auth_backends`，为了让权限层能回 403 + 具体 code），
    于是 `user.is_authenticated` 不再蕴含「账号正常」。
    需登录的接口由 `IsAuthenticatedAndActive` 兜住；**游客也能读的接口**
    （`AllowAny`）走不到权限类，得在可见性函数里自己判一次，
    否则被封禁的会话在那些接口上会被当成正常登录用户，比游客看得多。

    注意不含「禁言」：禁言只禁放团/报名/评价，不影响读。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_banned", False)) or not getattr(user, "is_active", False)


class IsAuthenticatedAndActive(permissions.BasePermission):
    """已登录、未封禁、未注销。

    三条拒绝路径的落地：
    - 未登录 → 返回 False，DRF 抛 `NotAuthenticated`，处理器拨回 **401 `not_authenticated`**；
    - 封禁 → 403 `account_banned`；
    - 注销（`is_active=False`）→ 403 `account_deactivated`。
    """

    message = "你的账号目前无法进行此项操作。"
    code = "permission_denied"

    def _deny(self, exc) -> bool:
        """把拒绝原因写到实例上，供 DRF 的 `permission_denied()` 读走。"""
        self.message = exc.default_detail
        self.code = exc.default_code
        return False

    def has_permission(self, request, view) -> bool:
        from common.exceptions import AccountBanned, AccountDeactivated

        user = request.user
        if not (user and user.is_authenticated):
            return False  # → 401，不是 403
        # 封禁会同时置 is_active=False（见 apps.accounts.services.ban_user），
        # 所以必须先判封禁，否则封禁号会被报成「已注销」。
        if getattr(user, "is_banned", False):
            return self._deny(AccountBanned)
        if not user.is_active:
            return self._deny(AccountDeactivated)
        return True


class IsNotMuted(IsAuthenticatedAndActive):
    """在「已登录且账号正常」之上，额外要求未被禁言（禁言者不能放团/报名/评价）。"""

    def has_permission(self, request, view) -> bool:
        from common.exceptions import AccountMuted

        if not super().has_permission(request, view):
            return False
        if getattr(request.user, "is_muted", False):
            return self._deny(AccountMuted)
        return True


def deny_like(outer: permissions.BasePermission, inner: permissions.BasePermission) -> bool:
    """把内层权限类的拒绝理由搬到外层实例上，然后返回 False。

    DRF 只会读**自己实例化的那个**权限对象的 `message` / `code`
    （`check_permissions` 里的 `getattr(permission, ...)`），
    所以组合式权限类里 `return Inner().has_permission(...)` 会把 code 丢掉。
    """
    outer.message = getattr(inner, "message", None)
    outer.code = getattr(inner, "code", None)
    return False


class ReadOnly(permissions.BasePermission):
    """只允许安全方法，用于游客可读的公开接口。"""

    def has_permission(self, request, view) -> bool:
        return request.method in permissions.SAFE_METHODS
