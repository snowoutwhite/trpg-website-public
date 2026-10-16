"""统一错误响应格式。"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

# 状态码 → 默认错误码与中文提示
_DEFAULT_CODES: dict[int, tuple[str, str]] = {
    status.HTTP_400_BAD_REQUEST: ("bad_request", "本次提交内容有误，请检查后重新提交。"),
    status.HTTP_401_UNAUTHORIZED: ("not_authenticated", "请先登录。"),
    status.HTTP_403_FORBIDDEN: ("permission_denied", "你没有权限进行此操作。"),
    status.HTTP_404_NOT_FOUND: ("not_found", "未找到相关内容。"),
    status.HTTP_405_METHOD_NOT_ALLOWED: ("method_not_allowed", "此操作暂不支持。"),
    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: ("payload_too_large", "上传内容过大。"),
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: ("unsupported_media_type", "本站不支持此类文件。"),
    status.HTTP_429_TOO_MANY_REQUESTS: ("throttled", "操作过于频繁，请稍后再试。"),
}


class ApiError(exceptions.APIException):
    """业务异常基类：带机器可读 code，方便前端分支处理。"""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "business_error"
    default_detail = "操作失败"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(detail=message or self.default_detail, code=code or self.default_code)
        if status is not None:
            self.status_code = status


class AuthRequired(ApiError):
    """401：未登录。

    会话认证没有 `WWW-Authenticate` 头，DRF 会把 `NotAuthenticated` 降级成 403，
    所以 `api_exception_handler` 会把它拉回 401；需要在 service 层显式表达时用这个类。
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "not_authenticated"
    default_detail = "请先登录。"


class Forbidden(ApiError):
    """403：已登录，但身份 / 角色 / 归属 / 账号状态不允许这个操作。"""

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "permission_denied"
    default_detail = "你没有权限进行此操作。"


class NotVisible(ApiError):
    """404：对方看不见的对象。不用 403，403 等于承认「它存在，只是你不能看」。"""

    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "未找到相关内容。"


# --------------------------------------------------------------------------
# 账号处置（禁言 / 封禁 / 注销）：全站同一组 code（缺陷 D4）
#
# 通用的 `permission_denied` 认不出「你被禁言了」，前端就做不了针对性引导

# 「账号状态不允许」那一格的落地，权限类与 service 层都只准用这三个，
# 不要在各 app 里另起名字。
# --------------------------------------------------------------------------


class AccountMuted(Forbidden):
    """403：被禁言。禁言只禁「放团 / 报名 / 评价」。"""

    default_code = "account_muted"
    default_detail = "你的账号当前处于禁言状态，暂不能放团、报名或提交评价。"


class AccountBanned(Forbidden):
    """403：被封禁。封禁同时置 `is_active=False`，所以判定顺序上要排在注销前面。"""

    default_code = "account_banned"
    default_detail = "你的账号已被封禁，无法执行此操作。"


class AccountDeactivated(Forbidden):
    """403：已注销（`is_active=False` 且不是封禁）。"""

    default_code = "account_deactivated"
    default_detail = "这个账号已注销。"


def _extract(exc: Exception, response_data: Any) -> tuple[str, str, Any]:
    """从 DRF 的原始响应体里拆出 code / message / detail。"""
    code = getattr(exc, "default_code", None) or "error"
    detail = None
    message = ""

    if isinstance(response_data, dict):
        raw_detail = response_data.get("detail")
        if raw_detail is not None and len(response_data) == 1:
            message = str(raw_detail)
            code = getattr(raw_detail, "code", None) or code
        else:
            detail = {k: _stringify(v) for k, v in response_data.items()}
            message = "表单中有若干项需要修改，请检查后重新提交。"
            code = "validation_error"
    elif isinstance(response_data, list):
        detail = {"non_field_errors": _stringify(response_data)}
        message = "表单中有若干项需要修改，请检查后重新提交。"
        code = "validation_error"
    else:
        message = str(response_data)

    return code, message, detail


def _stringify(value: Any) -> Any:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return {k: _stringify(v) for k, v in value.items()}
    return str(value)


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)
    if response is None:
        # 非 DRF 异常（500）交给 Django 处理，不在这里吞掉堆栈。
        return None

    # 「未登录」一律 401，不接受 DRF 的降级。
    # DRF 的 `APIView.handle_exception` 看到 `NotAuthenticated` 时会去问认证类要
    # `WWW-Authenticate` 头，而 `SessionAuthentication.authenticate_header()` 返回 None，
    # 于是它把状态码就地改成 403 —— 游客与「登录了但没权限」就分不开了。
    # 这里统一拨回来，各 app 才不用各写一份 LoginRequired（第 5 节状态码矩阵）。
    if isinstance(exc, exceptions.NotAuthenticated | exceptions.AuthenticationFailed):
        response.status_code = status.HTTP_401_UNAUTHORIZED

    code, message, detail = _extract(exc, response.data)
    fallback_code, fallback_message = _DEFAULT_CODES.get(
        response.status_code, ("error", "本次操作未能完成，请重试。")
    )
    if not code or code == "error":
        code = fallback_code
    if not message:
        message = fallback_message

    payload: dict[str, Any] = {"code": code, "message": message}
    if detail:
        payload["detail"] = detail
    response.data = {"error": payload}
    return response
