"""认证后端：登录闸与「会话取回闸」是两件事，这里把它们拆开。"""

from __future__ import annotations

from allauth.account.auth_backends import AuthenticationBackend
from django.contrib.auth import get_user_model


class BanAwareAuthenticationBackend(AuthenticationBackend):
    def user_can_authenticate(self, user) -> bool:
        """登录闸：封禁号一律拒绝（父类另外还会拒绝 `is_active=False`）。

        对 Django 的 `authenticate()`（后台登录等）来说封禁号就是登不进。
        allauth 登录接口多一步：allauth 的 `_check_password()` 只在**密码正确**时才调本函数，
        被拒的用户会被「暂存」并由适配器取回、送进 `AccountAdapter.pre_login()`，
        由它回 403 `account_banned`。密码错误的封禁号到不了这里。
        """
        if getattr(user, "is_banned", False):
            return False
        return super().user_can_authenticate(user)

    def get_user(self, user_id):
        """会话取回闸：被封禁 / 已停用的账号也照样取回来。

        注意这里**只是把用户取回来**，不代表放行 —— Django 层的 `request.user`
        由此变成那个真实用户，随后：
        - DRF 侧由 `common.authentication.AccountStateSessionAuthentication`
          认下来，权限类 `IsAuthenticatedAndActive` 给出 403 + `account_banned` /
          `account_deactivated`；
        - Django 后台侧由 `AdminSite.has_permission()` 的 `is_active` 拦住；
        - allauth headless 侧由 `common.middleware.BlockedAccountAllauthGuard`
          换回游客（它只看 `request.user.is_authenticated`，见该中间件的说明）。

        `django.contrib.auth.get_user()` 在本函数返回用户之后才做会话哈希校验，
        所以「改密码挤掉旧会话」这条保护不受影响 —— 放行的只是账号状态这一项。
        """
        user_model = get_user_model()
        try:
            return user_model._default_manager.get(pk=user_id)  # noqa: SLF001
        except user_model.DoesNotExist:
            return None
