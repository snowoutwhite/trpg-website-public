"""账号域接口。

管理动作（审批 GM 申请、封禁、禁言、生成邀请码）一律走 Django admin，不开放 API。
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import GMApplication
from apps.accounts.serializers import (
    AvatarInputSerializer,
    GMApplicationInputSerializer,
    GMApplicationSerializer,
    MeSerializer,
    NicknameInputSerializer,
)
from apps.accounts.services import (
    apply_for_gm,
    change_nickname,
    clear_avatar,
    deactivate_account,
    set_avatar,
)
from common.permissions import IsAuthenticatedAndActive


class MeView(APIView):
    """GET/PATCH /api/v1/accounts/me/ —— 只服务当前登录者，永远不接受 user id 参数。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get_throttles(self):
        """PATCH 也能改昵称，必须落在与 me/nickname/ 同一个限速桶里。

        否则它就是绕过 `nickname_change` 配额的旁路：可以无限次试昵称，
        把这个接口当成「某昵称是否已被占用」的枚举器。
        """
        if self.request.method == "PATCH":
            self.throttle_scope = NicknameView.throttle_scope
        return super().get_throttles()

    def get(self, request: Request) -> Response:
        return Response(MeSerializer(request.user).data)

    def patch(self, request: Request) -> Response:
        nickname = request.data.get("nickname")
        if nickname is not None:
            serializer = NicknameInputSerializer(data={"nickname": nickname})
            serializer.is_valid(raise_exception=True)
            change_nickname(request.user, serializer.validated_data["nickname"])
        return Response(MeSerializer(request.user).data)


class NicknameView(APIView):
    """POST /api/v1/accounts/me/nickname/ —— 改昵称（30 天一次）。"""

    permission_classes = [IsAuthenticatedAndActive]
    throttle_scope = "nickname_change"

    def post(self, request: Request) -> Response:
        serializer = NicknameInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = change_nickname(request.user, serializer.validated_data["nickname"])
        return Response(MeSerializer(user).data)


class AvatarView(APIView):
    """POST/DELETE /api/v1/accounts/me/avatar/ —— 上传或清除头像。"""

    permission_classes = [IsAuthenticatedAndActive]
    throttle_scope = "upload"

    def post(self, request: Request) -> Response:
        serializer = AvatarInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = set_avatar(request.user, serializer.validated_data["avatar"])
        return Response(MeSerializer(user).data)

    def delete(self, request: Request) -> Response:
        user = clear_avatar(request.user)
        return Response(MeSerializer(user).data)


class GMApplicationView(APIView):
    """GET/POST /api/v1/accounts/me/gm-application/ —— 查看/提交自己的 GM 申请。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "gm_application"
        return super().get_throttles()

    def get(self, request: Request) -> Response:
        application = (
            GMApplication.objects.filter(applicant=request.user).order_by("-created_at").first()
        )
        if application is None:
            return Response({"application": None})
        return Response({"application": GMApplicationSerializer(application).data})

    def post(self, request: Request) -> Response:
        serializer = GMApplicationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application = apply_for_gm(request.user, serializer.validated_data["reason"])
        return Response(
            GMApplicationSerializer(application).data, status=status.HTTP_201_CREATED
        )


class DeactivateView(APIView):
    """POST /api/v1/accounts/me/deactivate/ —— 注销：匿名化保留，不物理删除。"""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request) -> Response:
        from django.contrib.auth import logout

        deactivate_account(request.user)
        logout(request)
        return Response({"detail": "账号已注销"}, status=status.HTTP_200_OK)
