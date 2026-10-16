"""个人空间与自己的卡片接口。"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.profiles.serializers import (
    MyGMCardSerializer,
    MyPlayerCardSerializer,
    PublicProfileSerializer,
)
from apps.profiles.services import ensure_gm_card, ensure_player_card
from common.exceptions import Forbidden
from common.permissions import IsAuthenticatedAndActive


class NoGMCard(Forbidden):
    """业务规则与安全约束。"""

    default_code = "no_gm_card"
    default_detail = "你尚未成为 GM，暂无 GM 卡。"


class PublicProfileView(APIView):
    """GET /api/v1/profiles/users/<id>/ —— 任何人可看的个人空间，绝不含邮箱。"""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id, is_deactivated=False, is_banned=False)
        data = {
            "user": user,
            "player_card": ensure_player_card(user),
            "gm_card": ensure_gm_card(user) if user.is_gm else None,
        }
        return Response(PublicProfileSerializer(data).data)


class MyPlayerCardView(APIView):
    """GET/PATCH /api/v1/profiles/me/player-card/"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        card = ensure_player_card(request.user)
        return Response(MyPlayerCardSerializer(card).data)

    def patch(self, request: Request) -> Response:
        card = ensure_player_card(request.user)
        serializer = MyPlayerCardSerializer(card, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MyGMCardView(APIView):
    """GET/PATCH /api/v1/profiles/me/gm-card/ —— 仅 GM 可用。"""

    permission_classes = [IsAuthenticatedAndActive]

    def _get_card(self, request: Request):
        if not request.user.is_gm:
            raise NoGMCard()
        return ensure_gm_card(request.user)

    def get(self, request: Request) -> Response:
        return Response(MyGMCardSerializer(self._get_card(request)).data)

    def patch(self, request: Request) -> Response:
        card = self._get_card(request)
        serializer = MyGMCardSerializer(card, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
