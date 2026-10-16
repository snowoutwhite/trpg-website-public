"""allauth 适配器：把站内附加字段写进 User，按站点规则控制注册开放，并在登录时明示封禁。"""

from __future__ import annotations

from http import HTTPStatus

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.http import HttpRequest

#: 登录接口对「邮箱密码都对、但账号已封禁」给出的机器码，与 DRF 侧
#: `common.exceptions.AccountBanned` 同名，前端按同一个 code 认。
ACCOUNT_BANNED_CODE = "account_banned"
ACCOUNT_BANNED_LOGIN_MESSAGE = "你的账号已被封禁，目前无法登录。"

#: allauth 在调 `pre_login()` **之前**就往 session 里记了一条「password 认证」
#: （`account/internal/flows/login.py::perform_password_login` → `record_authentication`）。
#: 键名取自同一文件的 `AUTHENTICATION_METHODS_SESSION_KEY`；不从 internal 模块 import，
#: 这里写死并由测试钉住（`test_adversarial_banned_login.py` 的「不留认证记录」一格）。
_AUTHENTICATION_METHODS_SESSION_KEY = "account_authentication_methods"


class AccountAdapter(DefaultAccountAdapter):
    def save_user(self, request: HttpRequest, user, form, commit: bool = True):
        """在用户首次落库之前写入昵称（昵称有唯一约束，不能留空再补）。"""
        user = super().save_user(request, user, form, commit=False)
        nickname = (form.cleaned_data.get("nickname") or "").strip()
        if nickname:
            user.nickname = nickname
        if commit:
            user.save()
        return user

    def pre_login(self, request: HttpRequest, user, **kwargs):
        """业务规则与安全约束。"""
        if getattr(user, "is_banned", False):
            # 不给封禁号在 session 里留「已通过密码认证」的记录：同一浏览器随后换号登录时，
            # allauth 会把这份记录原样放进响应的 `data.methods`，封禁号的邮箱就跟着出去了。
            request.session.pop(_AUTHENTICATION_METHODS_SESSION_KEY, None)
            raise ImmediateHttpResponse(response=_banned_response(request))
        return super().pre_login(request, user, **kwargs)


def _banned_response(request: HttpRequest):
    # headless 模块在 HEADLESS_ONLY 下必装；放函数体里是为了不让 adapter 模块在导入期
    # 就把 headless 的 URL / 设置链拉起来。
    from allauth.headless.internal.restkit.response import APIResponse

    return APIResponse(
        request,
        errors=[{"code": ACCOUNT_BANNED_CODE, "message": ACCOUNT_BANNED_LOGIN_MESSAGE}],
        status=HTTPStatus.FORBIDDEN,
    )
