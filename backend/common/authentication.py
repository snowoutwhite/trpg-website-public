"""全站 DRF 认证类。

只有一个类，改的也只有一行判断，但它是「封禁号回 403 而不是 401」这件事的另一半
（前一半在 `apps.accounts.auth_backends.BanAwareAuthenticationBackend.get_user`）。
"""

from __future__ import annotations

from rest_framework.authentication import SessionAuthentication


class AccountStateSessionAuthentication(SessionAuthentication):
    """会话认证：**不**因为 `is_active=False` 把用户丢掉。"""

    def authenticate(self, request):
        user = getattr(request._request, "user", None)  # noqa: SLF001
        if not user or not user.is_authenticated:
            return None

        self.enforce_csrf(request)
        return (user, None)
