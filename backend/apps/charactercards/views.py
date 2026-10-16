"""角色卡接口：卡池（游客可浏览）、我的卡 CRUD、文件版本、鉴权下载。

红线：源文件只经 `CardDownloadView` 下发，任何列表/详情都不回传存储路径。
"""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.charactercards import services
from apps.charactercards.models import CharacterCard, CharacterCardFile
from common.exceptions import ApiError
from common.files import protected_file_response
from common.pagination import StandardPagination
from common.params import parse_pk
from common.permissions import IsAuthenticatedAndActive

from .serializers import (
    CardFileSerializer,
    CardFileUploadSerializer,
    MyCardSerializer,
    PublicCardSerializer,
)


class LoginRequired(ApiError):
    """显式 401。

    DRF 在没有 `WWW-Authenticate` 头（会话认证就是这种）时会把 NotAuthenticated 降级成 403，
    而卡池的口径是「游客能浏览、不能下载」，需要把「请先登录」和「你没权限」区分开。
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "not_authenticated"
    default_detail = "请先登录后再下载角色卡。"


class CardFileMissing(ApiError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "card_file_missing"
    default_detail = "这张卡还没有文件。"


class CardPoolView(ListAPIView):
    """GET /api/v1/charactercards/pool/ —— 角色卡池，游客可浏览。

    这里**保留会话认证**（不清 authentication_classes）：只读 GET 不触发 CSRF 校验，
    但需要知道当前登录者才能正确回 `can_download`。

    `?ordering=` 只认白名单 `CARD_POOL_ORDERING`，认不出的值回落默认序（与团列表同口径）。
    """

    permission_classes = [AllowAny]
    serializer_class = PublicCardSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        params = self.request.query_params
        raw_owner = params.get("owner", "").strip()
        owner_id = parse_pk(raw_owner) if raw_owner else None
        if raw_owner and owner_id is None:
            # 非法的 owner（超长数字、全角数字…）一律当「查不到」，
            # 既不把参数送进 DB 打成 500，也不用报错暴露校验细节。
            return CharacterCard.objects.none()
        return services.public_pool_queryset(
            rule_system=params.get("rule_system", "").strip(),
            status=params.get("status", "").strip(),
            owner_id=owner_id,
        ).order_by(*_pool_ordering(params.get("ordering", "").strip()))


#: 卡池排序白名单。`""` = 默认序，与 `CharacterCard.Meta.ordering` 一致（显式写出来，
#: 免得 `order_by()` 覆盖掉 Meta 之后默认序变成「数据库爱怎么排怎么排」）。
#: `plays` 按参团次数降序，同次数再按默认序，保证分页跨页稳定、不漏不重。
#: 只放这两种：放开任意字段等于给出一条排序信道（理由同 `games.views.GAME_ORDERING_WHITELIST`）。
CARD_POOL_ORDERING = {
    "": ("-created_at", "-id"),
    "plays": ("-play_count", "-created_at", "-id"),
}


def _pool_ordering(value: str) -> tuple[str, ...]:
    return CARD_POOL_ORDERING.get(value, CARD_POOL_ORDERING[""])


class CardDetailView(APIView):
    """GET /api/v1/charactercards/<pk>/ —— 单张卡的公开元数据。

    私密卡对非卡主一律 404（不暴露存在性，见 `_deny`）；公开卡人人可读。
    """

    permission_classes = [AllowAny]

    def get(self, request: Request, pk: int) -> Response:
        card = get_object_or_404(CharacterCard, pk=pk)
        if not services.can_view_card(request.user, card):
            _deny(request, card)
        serializer_class = (
            MyCardSerializer
            if getattr(request.user, "pk", None) == card.owner_id
            else PublicCardSerializer
        )
        return Response(serializer_class(card, context={"request": request}).data)


class MyCardListCreateView(APIView):
    """GET/POST /api/v1/charactercards/mine/ —— 我的卡列表与建卡。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        queryset = services.my_cards_queryset(
            request.user, status=request.query_params.get("status", "").strip()
        )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = MyCardSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request: Request) -> Response:
        serializer = MyCardSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        card = services.create_card(
            request.user,
            name=serializer.validated_data["name"],
            rule_system=serializer.validated_data.get("rule_system", ""),
            is_public=serializer.validated_data.get("is_public", False),
            note=serializer.validated_data.get("note", ""),
        )
        return Response(
            MyCardSerializer(card, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class MyCardDetailView(APIView):
    """GET/PATCH /api/v1/charactercards/mine/<pk>/ —— 改元数据、切换公开 / 撕卡。"""

    permission_classes = [IsAuthenticatedAndActive]

    def _get_card(self, request: Request, pk: int) -> CharacterCard:
        return get_object_or_404(CharacterCard, pk=pk, owner=request.user)

    def get(self, request: Request, pk: int) -> Response:
        card = self._get_card(request, pk)
        return Response(MyCardSerializer(card, context={"request": request}).data)

    def patch(self, request: Request, pk: int) -> Response:
        card = self._get_card(request, pk)
        serializer = MyCardSerializer(
            card, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MyCardFilesView(APIView):
    """GET/POST /api/v1/charactercards/mine/<pk>/files/ —— 版本列表与上传新版本。"""

    permission_classes = [IsAuthenticatedAndActive]
    throttle_scope = "upload"

    def _get_card(self, request: Request, pk: int) -> CharacterCard:
        return get_object_or_404(CharacterCard, pk=pk, owner=request.user)

    def get(self, request: Request, pk: int) -> Response:
        card = self._get_card(request, pk)
        versions = CharacterCardFile.objects.filter(card=card).select_related("uploaded_by")
        return Response({"results": CardFileSerializer(versions, many=True).data})

    def post(self, request: Request, pk: int) -> Response:
        card = self._get_card(request, pk)
        serializer = CardFileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        version = services.add_file_version(
            card, serializer.validated_data["file"], uploaded_by=request.user
        )
        return Response(CardFileSerializer(version).data, status=status.HTTP_201_CREATED)


class CardDownloadView(APIView):
    """GET /api/v1/charactercards/<pk>/download/ —— 鉴权后经受保护通道下发源文件。

    - 公开卡 + 游客：401（卡池只给浏览，不给下载；登录就能下）。
    - 公开卡 + 封禁/注销号：403。
    - 私密卡 + 非卡主：404（不承认它存在，见 `_deny`）。
    - `?version=N` 取指定版本，默认最新版。
    """

    permission_classes = [AllowAny]

    def get(self, request: Request, pk: int) -> Response:
        card = get_object_or_404(CharacterCard, pk=pk)
        if not services.can_view_file(request.user, card):
            _deny(request, card)

        requested = request.query_params.get("version", "").strip()
        versions = CharacterCardFile.objects.filter(card=card)
        if requested:
            number = parse_pk(requested)
            version = None if number is None else versions.filter(version=number).first()
        else:
            version = versions.order_by("-version").first()
        if version is None or not version.file:
            raise CardFileMissing()

        return protected_file_response(version.file, download_name=version.original_name)


def _deny(request: Request, card: CharacterCard) -> None:
    """业务规则与安全约束。"""
    if not card.is_public and getattr(request.user, "pk", None) != card.owner_id:
        raise Http404
    if not getattr(request.user, "is_authenticated", False):
        raise LoginRequired()
    raise PermissionDenied("这张卡不存在，或尚未公开。")
