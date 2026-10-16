"""站长内容接口。

公开读：
- `GET /api/v1/home/` —— 首页一次要的全部内容（站级文案 + 规则预设 + 快速选择 +
  最新一条生效公告及本人是否已读 + 精选照片）。
- `GET /api/v1/home/featured-photos/<pk>/file/?size=` —— 精选照片的字节出口。
- `GET /api/v1/announcements/` —— 公告历史（分页，只列生效且已到时间的）。

预告（`published_at` 在未来）到点后的补推**只**由生产 cron 的
`manage.py announcements_publish_due` 负责；公开读路径不触发任何写
。

staff 写：前缀 `/api/v1/home/admin/`，权限一律 `IsSiteStaff`（`is_staff`）。
口径与第 5.1 节一致：游客 401、登录但不是 staff 403。
"""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gallery.models import PHOTO_PUBLIC, SIZE_FIELDS, SIZE_PREVIEW, SIZE_THUMB, Photo
from apps.homecontent import services
from apps.homecontent.models import QuickEntry, RuleSystemPreset, SiteAnnouncement
from apps.homecontent.serializers import (
    AdminFeaturedCandidateSerializer,
    FeaturedPhotoSerializer,
    FeaturePhotoSerializer,
    HomeConfigWriteSerializer,
    HomeSiteCopySerializer,
    ImageUploadSerializer,
    QuickEntrySerializer,
    QuickEntryWriteSerializer,
    RuleSystemPresetSerializer,
    RuleSystemPresetWriteSerializer,
    SiteAnnouncementSerializer,
    SiteAnnouncementWriteSerializer,
)
from apps.siteconfig.services import get_config
from common.files import protected_file_response
from common.pagination import StandardPagination
from common.params import parse_pk
from common.permissions import IsAuthenticatedAndActive

#: 首页照片墙一次给多少张。首页是个门面，不是相册列表，不分页、给个上限就够。
FEATURED_PHOTO_LIMIT = 12


class IsSiteStaff(IsAuthenticatedAndActive):
    """站主写接口：登录 + 账号正常 + `is_staff`。

    继承 `IsAuthenticatedAndActive` 是为了把「未登录 → 401」「封禁/注销 → 403 带
    具体 code」那两条路径原样继承下来；这里只在最后多加一道 `is_staff`。
    """

    message = "只有站主能修改站长内容"
    code = "permission_denied"

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return bool(getattr(request.user, "is_staff", False))


# --------------------------------------------------------------------------
# 公开读
# --------------------------------------------------------------------------


def _announcement_context(request: Request, announcements) -> dict:
    """一次把「当前用户收到的公告通知」查出来，避免列表里逐条查。"""
    read_map = {}
    user = getattr(request, "user", None)
    rows = [a for a in announcements if a is not None]
    if rows and getattr(user, "is_authenticated", False):
        from django.contrib.contenttypes.models import ContentType

        from apps.notifications import events
        from apps.notifications.models import Notification

        content_type = ContentType.objects.get_for_model(SiteAnnouncement)
        for notification in Notification.objects.filter(
            recipient=user,
            event=events.SITE_ANNOUNCEMENT,
            target_content_type=content_type,
            target_object_id__in=[a.pk for a in rows],
        ).only("id", "read_at", "target_object_id"):
            read_map[notification.target_object_id] = notification
    return {"request": request, "read_map": read_map}


class HomeView(APIView):
    """GET /api/v1/home/ —— 首页要的全部内容，一次给完。

    游客可读；登录用户多拿到「公告是否已读」，以及 `members` 可见范围下的精选照片。
    """

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        config = get_config()
        announcement = services.latest_announcement()
        context = _announcement_context(request, [announcement])

        photos_visible = services.can_see_featured_photos(request.user)
        photos = list(services.featured_photos()[:FEATURED_PHOTO_LIMIT]) if photos_visible else []

        return Response(
            {
                "site": HomeSiteCopySerializer(config).data,
                "rule_presets": RuleSystemPresetSerializer(
                    RuleSystemPreset.objects.all(), many=True, context={"request": request}
                ).data,
                "quick_entries": QuickEntrySerializer(
                    QuickEntry.objects.all(), many=True, context={"request": request}
                ).data,
                "announcement": (
                    SiteAnnouncementSerializer(announcement, context=context).data
                    if announcement
                    else None
                ),
                "featured_photos": {
                    "enabled": config.featured_photos_enabled,
                    "visibility": config.featured_photos_visibility,
                    "visible": photos_visible,
                    "results": FeaturedPhotoSerializer(
                        photos, many=True, context={"request": request}
                    ).data,
                },
            }
        )


class AnnouncementListView(ListAPIView):
    """GET /api/v1/announcements/ —— 公告历史，游客可读，分页。"""

    permission_classes = [AllowAny]
    serializer_class = SiteAnnouncementSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return services.active_announcements()

    def get_serializer_context(self):
        page = getattr(self, "_page_rows", [])
        return _announcement_context(self.request, page)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        self._page_rows = list(page if page is not None else queryset)
        serializer = self.get_serializer(self._page_rows, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class FeaturedPhotoFileView(APIView):
    """GET /api/v1/home/featured-photos/<pk>/file/?size=thumb|preview

    精选照片的字节出口。相册本体的 `PhotoFileView` 是**一律需登录**的，
    这里是站主显式开的一个小口子，因此三道闸缺一不可：
    1. 站级开关 `featured_photos_enabled`；
    2. 可见范围 `featured_photos_visibility` 与当前登录态；
    3. 这张照片当下确实既是 `is_featured` 又是 `status=public`。
    任何一道不过一律 404 —— 不回 403，免得连「这张照片存在」都被问出来。
    只放行 thumb / preview 两档：首页不需要原图，原图仍只在相册里（需登录）拿得到。
    """

    permission_classes = [AllowAny]

    def get(self, request: Request, pk: int):
        if not services.can_see_featured_photos(request.user):
            raise Http404
        # `<int:pk>` 只保证是数字，不保证落在 32 位整数里：越界值在 PostgreSQL 上会
        # 让查询自己抛 DataError（500），在 SQLite 上又静默查空 —— 两个后端行为不一致。
        # 统一走 `common.params.parse_pk`，越界一律当「查不到」（404，与不存在的 pk 同答）。
        pk = parse_pk(pk)
        if pk is None:
            raise Http404
        photo = services.featured_photos().filter(pk=pk).first()
        if photo is None:
            raise Http404
        size = request.query_params.get("size", SIZE_THUMB).strip().lower()
        if size not in (SIZE_THUMB, SIZE_PREVIEW):
            size = SIZE_THUMB
        file_field = getattr(photo, SIZE_FIELDS[size], None)
        if not file_field:
            raise Http404
        return protected_file_response(
            file_field,
            download_name=f"featured-{photo.pk}-{size}.webp",
            content_type="image/webp",
            as_attachment=False,
        )


# --------------------------------------------------------------------------
# staff 写
# --------------------------------------------------------------------------


class AdminHomeView(APIView):
    """GET /api/v1/home/admin/ —— 站主的可编辑全量视图（含未生效的公告）。"""

    permission_classes = [IsSiteStaff]

    def get(self, request: Request) -> Response:
        config = get_config()
        announcements = list(SiteAnnouncement.objects.select_related("author")[:50])
        context = _announcement_context(request, announcements)
        return Response(
            {
                "config": HomeConfigWriteSerializer(config).data,
                "rule_presets": RuleSystemPresetSerializer(
                    RuleSystemPreset.objects.all(), many=True, context={"request": request}
                ).data,
                "quick_entries": QuickEntrySerializer(
                    QuickEntry.objects.all(), many=True, context={"request": request}
                ).data,
                "announcements": [
                    {
                        **SiteAnnouncementSerializer(row, context=context).data,
                        "is_active": row.is_active,
                        "notified_at": row.notified_at,
                        "notified_count": row.notified_count,
                    }
                    for row in announcements
                ],
            }
        )


class AdminConfigView(APIView):
    """PATCH /api/v1/home/admin/config/ —— 改首页那几格站级文案与开关。"""

    permission_classes = [IsSiteStaff]

    def patch(self, request: Request) -> Response:
        config = get_config()
        serializer = HomeConfigWriteSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(HomeConfigWriteSerializer(get_config()).data)


class _StaffListCreateView(APIView):
    """列表 + 新建的公共骨架（规则预设 / 快速选择共用）。"""

    permission_classes = [IsSiteStaff]
    model = None
    read_serializer = None
    write_serializer = None

    def get(self, request: Request) -> Response:
        return Response(
            self.read_serializer(
                self.model.objects.all(), many=True, context={"request": request}
            ).data
        )

    def post(self, request: Request) -> Response:
        serializer = self.write_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(
            self.read_serializer(instance, context={"request": request}).data,
            status=http_status.HTTP_201_CREATED,
        )


class _StaffDetailView(APIView):
    """改 + 删的公共骨架。"""

    permission_classes = [IsSiteStaff]
    model = None
    read_serializer = None
    write_serializer = None

    def get_object(self, pk: int):
        return get_object_or_404(self.model, pk=pk)

    def patch(self, request: Request, pk: int) -> Response:
        instance = self.get_object(pk)
        serializer = self.write_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(self.read_serializer(instance, context={"request": request}).data)

    def delete(self, request: Request, pk: int) -> Response:
        instance = self.get_object(pk)
        services.delete_stored_images(instance)
        instance.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class AdminRulePresetListView(_StaffListCreateView):
    """GET/POST /api/v1/home/admin/rule-presets/"""

    model = RuleSystemPreset
    read_serializer = RuleSystemPresetSerializer
    write_serializer = RuleSystemPresetWriteSerializer


class AdminRulePresetDetailView(_StaffDetailView):
    """PATCH/DELETE /api/v1/home/admin/rule-presets/<pk>/"""

    model = RuleSystemPreset
    read_serializer = RuleSystemPresetSerializer
    write_serializer = RuleSystemPresetWriteSerializer


class AdminQuickEntryListView(_StaffListCreateView):
    """GET/POST /api/v1/home/admin/quick-entries/"""

    model = QuickEntry
    read_serializer = QuickEntrySerializer
    write_serializer = QuickEntryWriteSerializer


class AdminQuickEntryDetailView(_StaffDetailView):
    """PATCH/DELETE /api/v1/home/admin/quick-entries/<pk>/"""

    model = QuickEntry
    read_serializer = QuickEntrySerializer
    write_serializer = QuickEntryWriteSerializer


class _ImageUploadView(APIView):
    """multipart 上传的公共骨架，限速走 `upload` 档（与相册一致）。"""

    permission_classes = [IsSiteStaff]
    throttle_scope = "upload"
    model = None
    read_serializer = None

    def apply(self, instance, uploaded_file):  # pragma: no cover - 子类必须实现
        raise NotImplementedError

    def post(self, request: Request, pk: int) -> Response:
        instance = get_object_or_404(self.model, pk=pk)
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = self.apply(instance, serializer.validated_data["file"])
        return Response(self.read_serializer(instance, context={"request": request}).data)


class AdminRulePresetImageView(_ImageUploadView):
    """POST /api/v1/home/admin/rule-presets/<pk>/image/ —— 一次生成三档。"""

    model = RuleSystemPreset
    read_serializer = RuleSystemPresetSerializer

    def apply(self, instance, uploaded_file):
        return services.set_preset_image(instance, uploaded_file)


class AdminQuickEntryImageView(_ImageUploadView):
    """POST /api/v1/home/admin/quick-entries/<pk>/image/"""

    model = QuickEntry
    read_serializer = QuickEntrySerializer

    def apply(self, instance, uploaded_file):
        return services.set_quick_entry_image(instance, uploaded_file)


class AdminAnnouncementListView(APIView):
    """GET/POST /api/v1/home/admin/announcements/

    新建时若公告当场就生效（`is_active` 且发布时间已到），立刻给全站活跃用户推送一轮。
    """

    permission_classes = [IsSiteStaff]

    def get(self, request: Request) -> Response:
        rows = list(SiteAnnouncement.objects.select_related("author")[:100])
        context = _announcement_context(request, rows)
        return Response(SiteAnnouncementSerializer(rows, many=True, context=context).data)

    def post(self, request: Request) -> Response:
        serializer = SiteAnnouncementWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from django.utils import timezone

        announcement = serializer.save(
            author=request.user,
            published_at=serializer.validated_data.get("published_at") or timezone.now(),
        )
        services.publish_announcement(announcement)
        context = _announcement_context(request, [announcement])
        return Response(
            SiteAnnouncementSerializer(announcement, context=context).data,
            status=http_status.HTTP_201_CREATED,
        )


class AdminAnnouncementDetailView(APIView):
    """PATCH/DELETE /api/v1/home/admin/announcements/<pk>/

    改完若公告变成「生效且已到时间」，补推一轮 —— 但 `notified_at` 已经落下的
    公告永远不会再推第二遍（`services.publish_announcement` 的幂等锚）。
    """

    permission_classes = [IsSiteStaff]

    def patch(self, request: Request, pk: int) -> Response:
        announcement = get_object_or_404(SiteAnnouncement, pk=pk)
        serializer = SiteAnnouncementWriteSerializer(
            announcement, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        announcement = serializer.save()
        services.publish_announcement(announcement)
        announcement.refresh_from_db()
        context = _announcement_context(request, [announcement])
        return Response(SiteAnnouncementSerializer(announcement, context=context).data)

    def delete(self, request: Request, pk: int) -> Response:
        announcement = get_object_or_404(SiteAnnouncement, pk=pk)
        announcement.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class AdminFeaturePhotoView(APIView):
    """POST /api/v1/home/admin/featured-photos/ —— body `{"photo": 1, "is_featured": true}`

    只有 `status=public` 的照片能被勾上（`photo_not_public`，400）。
    """

    permission_classes = [IsSiteStaff]

    def get(self, request: Request) -> Response:
        # 站主侧列**全部**精选，不套首页的 FEATURED_PHOTO_LIMIT：

        photos = list(services.featured_photos())
        return Response(
            FeaturedPhotoSerializer(photos, many=True, context={"request": request}).data
        )

    def post(self, request: Request) -> Response:
        serializer = FeaturePhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo = get_object_or_404(Photo, pk=serializer.validated_data["photo"])
        services.set_photo_featured(photo, serializer.validated_data["is_featured"])
        return Response({"id": photo.pk, "is_featured": photo.is_featured})


class AdminFeaturedCandidateView(ListAPIView):
    """GET /api/v1/home/admin/featured-photos/candidates/?game=<id>&page="""

    permission_classes = [IsSiteStaff]
    pagination_class = StandardPagination
    serializer_class = AdminFeaturedCandidateSerializer

    def get_queryset(self):
        queryset = (
            Photo.objects.filter(status=PHOTO_PUBLIC)
            .select_related("game")
            .order_by("-created_at", "-id")
        )
        raw_game = self.request.query_params.get("game")
        if raw_game is not None and raw_game.strip() != "":
            game_id = parse_pk(raw_game)
            # 写了但不合法（越界 / 非数字）当「没有此团」→ 空页，不悄悄退成全站
            queryset = queryset.filter(game_id=game_id) if game_id is not None else queryset.none()
        return queryset
