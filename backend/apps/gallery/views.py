"""相册接口。

可见性口径：
- **整个相册对游客关门**，一律 401（不是 403）—— 会话认证下 DRF 会把 NotAuthenticated
  降级成 403，所以这里和角色卡一样用显式的 `LoginRequired`。
- 看不见的照片一律 **404**，不用 403：403 等于承认「这张照片存在，只是你不能看」，
  待审与已下架的照片连存在性都不该外泄。

文件下发：三档都走 `PhotoFileView` + `common.files.protected_file_response()`，
没有任何一条路径会把 `MEDIA_ROOT/protected/gallery/...` 直接给出去。
"""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gallery import services
from apps.gallery.models import SIZE_FIELDS, SIZE_THUMB, Photo, PhotoReport
from apps.gallery.serializers import (
    HandleReportSerializer,
    ModerationReportSerializer,
    MyPhotoReportSerializer,
    PhotoReportCreateSerializer,
    PhotoSerializer,
    PhotoUploadSerializer,
    RejectPhotoSerializer,
)
from common.exceptions import ApiError
from common.files import protected_file_response
from common.pagination import StandardPagination
from common.permissions import IsAuthenticatedAndActive


class LoginRequired(ApiError):
    """显式 401：相册整体需登录，游客不该拿到 403（那是「登录了但没权限」的意思）。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "not_authenticated"
    default_detail = "相册需要登录后查看。"


class GalleryLoginRequired(IsAuthenticatedAndActive):
    """登录闸：游客 401，登录但封禁/注销 403。

    不能只写 `IsAuthenticatedAndActive` —— 会话认证没有 `WWW-Authenticate` 头，
    DRF 会把 `NotAuthenticated` 一路降级成 403，游客就分不清「要登录」和「没权限」了。
    这里在权限类里直接抛显式 401。
    """

    def has_permission(self, request, view) -> bool:
        if not getattr(request.user, "is_authenticated", False):
            raise LoginRequired()
        return super().has_permission(request, view)


class CanModerate(GalleryLoginRequired):
    """站主专属动作：走 Django 权限位 `gallery.moderate_photo`，不判断 is_superuser。"""

    message = "没有相册审核权限"

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return services.can_moderate(request.user)


def _get_game(pk: int):
    from apps.games.models import Game

    return get_object_or_404(Game, pk=pk)


def _visible_photo_or_404(request: Request, pk: int) -> Photo:
    """拿一张当前用户看得见的照片；看不见就 404（不泄露存在性）。"""
    photo = Photo.objects.select_related("uploader", "game").filter(pk=pk).first()
    if photo is None or not services.can_view_photo(request.user, photo):
        raise Http404
    return photo


class GamePhotoListView(APIView):
    """GET/POST /api/v1/gallery/games/<game_id>/photos/

    GET：登录用户看该团相册（分页）。普通用户只看得到 `public`，
    上传者额外看得到自己待审/被下架的那些，站主看全部。
    POST：仅本团 GM，且团已结团、还在上传窗口内。
    """

    permission_classes = [GalleryLoginRequired]
    pagination_class = StandardPagination

    def get_throttles(self):

        if self.request.method == "POST":
            self.throttle_scope = "upload"
        return super().get_throttles()

    def get(self, request: Request, game_id: int) -> Response:
        game = _get_game(game_id)
        queryset = services.visible_photos(request.user, game=game)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = PhotoSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request: Request, game_id: int) -> Response:
        game = _get_game(game_id)
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo = services.upload_photo(
            request.user,
            game,
            serializer.validated_data["file"],
            caption=serializer.validated_data.get("caption", ""),
        )
        return Response(
            PhotoSerializer(photo, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class PhotoDetailView(APIView):
    """GET/DELETE /api/v1/gallery/photos/<pk>/ —— 单张详情 / 删除（uploader 或站主）。"""

    permission_classes = [GalleryLoginRequired]

    def get(self, request: Request, pk: int) -> Response:
        photo = _visible_photo_or_404(request, pk)
        return Response(PhotoSerializer(photo, context={"request": request}).data)

    def delete(self, request: Request, pk: int) -> Response:
        photo = _visible_photo_or_404(request, pk)
        if photo.uploader_id != request.user.pk and not services.can_moderate(request.user):
            raise Http404
        services.delete_photo(photo)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PhotoFileView(APIView):
    """GET /api/v1/gallery/photos/<pk>/file/?size=thumb|preview|original

    唯一的图片字节出口。游客 401、看不见的照片 404、档位名不认识就退回缩略图。
    `as_attachment=False`：这是要放进 `<img src>` 的，必须内联展示。
    内容类型写死 `image/webp` —— 三档都是我们自己重新编码出来的 WebP，
    不存在「按用户传的文件名猜类型」那条 XSS 路径（common/files.py 的第 1 条边界）。
    """

    permission_classes = [GalleryLoginRequired]

    def get(self, request: Request, pk: int):
        photo = _visible_photo_or_404(request, pk)
        size = request.query_params.get("size", SIZE_THUMB).strip().lower()
        if size not in SIZE_FIELDS:
            size = SIZE_THUMB
        file_field = photo.file_for(size)
        if not file_field:
            raise Http404
        return protected_file_response(
            file_field,
            download_name=f"photo-{photo.pk}-{size}.webp",
            content_type="image/webp",
            as_attachment=False,
        )


class PhotoReportView(APIView):
    """POST /api/v1/gallery/photos/<pk>/report/ —— 举报 / 下架诉求入口。"""

    permission_classes = [GalleryLoginRequired]

    def post(self, request: Request, pk: int) -> Response:
        photo = _visible_photo_or_404(request, pk)
        serializer = PhotoReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = services.report_photo(
            request.user,
            photo,
            reason=serializer.validated_data["reason"],
            reason_text=serializer.validated_data.get("reason_text", ""),
        )
        return Response(
            MyPhotoReportSerializer(report).data, status=status.HTTP_201_CREATED
        )


class MyReportListView(ListAPIView):
    """GET /api/v1/gallery/reports/mine/ —— 举报人只能看自己的举报状态。"""

    permission_classes = [GalleryLoginRequired]
    serializer_class = MyPhotoReportSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return services.my_reports(self.request.user)


# --------------------------------------------------------------------------
# 站主侧（权限位 gallery.moderate_photo）
# --------------------------------------------------------------------------


class _PendingPhotoPagination(StandardPagination):
    """待审照片那一半的翻页参数（两个列表在同一个响应里，页码得分开）。"""

    page_query_param = "photos_page"


class _OpenReportPagination(StandardPagination):
    page_query_param = "reports_page"


class ModerationQueueView(APIView):
    """GET /api/v1/gallery/moderation/queue/ —— 待办：待审照片 + 未处理举报。

    **两个列表各自分页**（W5）：原来是两条全量列表，站点跑一阵之后这个接口会
    一次吐出成百上千行（还要为每张照片算三档 URL）。
    翻页参数分开：`?photos_page=` / `?reports_page=`，`page_size` 两边共用，上限 100。
    响应形状与全站分页一致，只是嵌在两个键下面。
    """

    permission_classes = [CanModerate]

    def get(self, request: Request) -> Response:
        return Response(
            {
                "pending_photos": self._page(
                    _PendingPhotoPagination(),
                    services.pending_moderation_queue(),
                    PhotoSerializer,
                    request,
                ),
                "open_reports": self._page(
                    _OpenReportPagination(),
                    services.open_reports_queue(),
                    ModerationReportSerializer,
                    request,
                ),
            }
        )

    def _page(self, paginator, queryset, serializer_class, request: Request) -> dict:
        rows = paginator.paginate_queryset(queryset, request, view=self)
        return {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer_class(rows, many=True, context={"request": request}).data,
        }


class ApprovePhotoView(APIView):
    """POST /api/v1/gallery/moderation/photos/<pk>/approve/"""

    permission_classes = [CanModerate]

    def post(self, request: Request, pk: int) -> Response:
        photo = get_object_or_404(Photo, pk=pk)
        services.approve_photo(photo)
        return Response(PhotoSerializer(photo, context={"request": request}).data)


class RejectPhotoView(APIView):
    """POST /api/v1/gallery/moderation/photos/<pk>/reject/"""

    permission_classes = [CanModerate]

    def post(self, request: Request, pk: int) -> Response:
        photo = get_object_or_404(Photo, pk=pk)
        serializer = RejectPhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reject_photo(photo, reason=serializer.validated_data.get("reason", ""))
        return Response(PhotoSerializer(photo, context={"request": request}).data)


class HandleReportView(APIView):
    """POST /api/v1/gallery/moderation/reports/<pk>/handle/

    body `{"action": "restored" | "taken_down" | "dismissed", "note": ""}`。
    处理完给举报人发 `PHOTO_REPORT_RESULT`（不带 actor，不暴露处理人身份）。
    """

    permission_classes = [CanModerate]

    def post(self, request: Request, pk: int) -> Response:
        report = get_object_or_404(PhotoReport.objects.select_related("photo"), pk=pk)
        serializer = HandleReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.handle_report(
            report,
            by=request.user,
            action=serializer.validated_data["action"],
            note=serializer.validated_data.get("note", ""),
        )
        report.refresh_from_db()
        return Response(ModerationReportSerializer(report, context={"request": request}).data)
