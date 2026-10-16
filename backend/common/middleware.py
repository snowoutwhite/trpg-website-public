"""全站中间件。

目前只有一件事：把封禁 / 停用账号挡在 allauth headless 之外。
"""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser

#: allauth headless 的 URLConf 自带 `app_name = "headless"`
#: （`allauth/headless/urls.py`），所以这里按**解析结果的 app 名**判断，
#: 而不是写死 `/_allauth/` 这个挂载路径（挂载点在 `config/urls.py`，可改）。
ALLAUTH_APP_NAME = "headless"


class BlockedAccountAllauthGuard:
    """allauth headless 侧：被封禁 / 停用的会话一律当游客看。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match is None or ALLAUTH_APP_NAME not in (match.app_names or []):
            return None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        if getattr(user, "is_banned", False) or not user.is_active:
            request.user = AnonymousUser()
        return None
