"""战报接口。视图只做鉴权、取对象、序列化；规则全在 `services.py`。"""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.games.models import Game
from apps.reports import importing, services
from apps.reports.models import VISIBILITY_PUBLIC, Report, ReportAttachment
from apps.reports.serializers import (
    AbuseInputSerializer,
    AttachmentUploadSerializer,
    DocumentImportSerializer,
    ImportTargetSerializer,
    ReportAttachmentSerializer,
    ReportCreateSerializer,
    ReportDetailSerializer,
    ReportListSerializer,
    ReportUpdateSerializer,
)
from apps.siteconfig.services import OTHER_SENTINEL, exclude_preset_rule_systems
from common.exceptions import Forbidden
from common.files import protected_file_response
from common.pagination import StandardPagination
from common.params import parse_pk
from common.permissions import IsAuthenticatedAndActive, is_account_blocked


class ReportNotEditable(Forbidden):
    default_code = "permission_denied"
    default_detail = "只能修改自己的战报"


# 主键筛选参数的解析统一走 `common.params.parse_pk`（位数闸 + 32 位范围闸，
# 三个 app 共用一份，理由见那个模块的文头）。
# 对抗测试：`tests/test_adversarial_reports.py::test_列表过滤器收到超长数字不得打成500`。


def _empty_page() -> Response:
    """与分页器同形状的空结果：非法筛选值一律当「查不到」，不暴露任何存在性线索。"""
    return Response({"count": 0, "next": None, "previous": None, "results": []})


def _visible_report(request: Request, pk: int) -> Report:
    """取一份当前用户看得见的战报；看不见就 404（不用 403 暴露其存在）。"""
    report = get_object_or_404(
        Report.objects.select_related("game", "game__gm", "author").prefetch_related("attachments"),
        pk=pk,
    )
    if not services.can_view(request.user, report):
        raise Http404
    return report


def _filter_rule_system(queryset, request: Request):
    """`?rule_system=` 按战报所属团的规则名筛；`__other__` 哨兵与团列表同一口径。

    列表与精选两个接口共用：前端「精选」那一档（游客只有这一档）也有规则筹码，
    只给一个接口加的话，游客点规则就只能退回本页过滤。
    """
    rule_system = request.query_params.get("rule_system", "").strip()
    if rule_system == OTHER_SENTINEL:
        return exclude_preset_rule_systems(queryset, field="game__rule_system")
    if rule_system:
        return queryset.filter(game__rule_system__iexact=rule_system)
    return queryset


def _paginated(view: APIView, request: Request, queryset, serializer_class) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request, view=view)
    serializer = serializer_class(page, many=True, context={"request": request})
    return paginator.get_paginated_response(serializer.data)


class ReportListCreateView(APIView):
    """GET /api/v1/reports/（游客可读，只给精选；?game=&author=&rule_system=&mine=）
    POST /api/v1/reports/（本人提交：团已结团且本人在团内到场）

    - `?rule_system=` 按战报所属团的规则名筛（大小写不敏感）；`__other__` 哨兵与团列表
      同口径：团的规则名不命中任何站级预设（空规则名也算）。
    - `?mine=1` 只留「我同团」的团的战报 —— 我主持的 + 我正式到场的，判据就是
      `services.member_game_ids`，与 same_game 可见性共用一份，不另起一套「到场」定义。
      游客 / 封禁会话没有「我」，直接回空页（与 `visible_queryset` 把封禁按游客算同口径）。
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticatedAndActive()]
        return [AllowAny()]

    def get(self, request: Request) -> Response:
        queryset = services.visible_queryset(request.user)
        for param, field in (("game", "game_id"), ("author", "author_id")):
            raw = request.query_params.get(param, "").strip()
            if not raw:
                continue
            pk = parse_pk(raw)
            if pk is None:
                return _empty_page()
            queryset = queryset.filter(**{field: pk})

        queryset = _filter_rule_system(queryset, request)

        if request.query_params.get("mine", "").strip() == "1":
            user = request.user
            if not getattr(user, "is_authenticated", False) or is_account_blocked(user):
                return _empty_page()
            queryset = queryset.filter(game_id__in=services.member_game_ids(user))
        return _paginated(self, request, queryset, ReportListSerializer)

    def post(self, request: Request) -> Response:
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        game: Game = data["game"]
        report, created = services.submit_report(
            request.user,
            game,
            title=data["title"],
            body_markdown=data.get("body_markdown", ""),
            visibility=data.get("visibility") or VISIBILITY_PUBLIC,
        )
        return Response(
            ReportDetailSerializer(report, context={"request": request}).data,
            status=http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK,
        )


class ReportDocumentImportView(APIView):
    """POST /api/v1/reports/import-document/（multipart：`game` + `file`）

    把 .docx / .txt 转成 Markdown 正文回给前端填进编辑框，**不落库、不建附件**。
    资格与写战报同一口径：本团已有自己那份战报的作者，或满足提交条件
    （已结团 + 本团 GM / 正式名单里到场）的人；走上传限速档（`upload`）。
    转换与安全规则全在 `importing.py`。
    """

    permission_classes = [IsAuthenticatedAndActive]
    throttle_scope = "upload"

    def post(self, request: Request) -> Response:
        # 先只校验 game 判资格，再看文件：没资格的人不该拿到「文件格式不对」之类的反馈
        target = ImportTargetSerializer(data=request.data)
        target.is_valid(raise_exception=True)
        services.assert_can_import(request.user, target.validated_data["game"])
        serializer = DocumentImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = importing.import_document(serializer.validated_data["file"])
        return Response(
            {
                "body_markdown": result.body_markdown,
                "truncated": result.truncated,
                "warnings": result.warnings,
            }
        )


class FeaturedReportListView(APIView):
    """GET /api/v1/reports/featured/ —— 站主精选的公开战报，游客可读（`?rule_system=` 同列表）。"""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        queryset = services.visible_queryset(request.user, featured_only=True)
        queryset = _filter_rule_system(queryset, request)
        return _paginated(self, request, queryset, ReportListSerializer)


class ReportDetailView(APIView):
    """GET / PUT / PATCH / DELETE /api/v1/reports/<pk>/。

    改只有作者能做；删是作者或持 `reports.moderate_report` 权限位的站主。
    """

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [IsAuthenticatedAndActive()]
        return [AllowAny()]

    def get(self, request: Request, pk: int) -> Response:
        report = _visible_report(request, pk)
        return Response(ReportDetailSerializer(report, context={"request": request}).data)

    def put(self, request: Request, pk: int) -> Response:
        return self._write(request, pk)

    def patch(self, request: Request, pk: int) -> Response:
        return self._write(request, pk)

    def _write(self, request: Request, pk: int) -> Response:
        report = _visible_report(request, pk)
        if not services.can_edit(request.user, report):
            raise ReportNotEditable()
        serializer = ReportUpdateSerializer(data=request.data, partial=request.method == "PATCH")
        serializer.is_valid(raise_exception=True)
        report = services.update_report(report, **serializer.validated_data)
        return Response(ReportDetailSerializer(report, context={"request": request}).data)

    def delete(self, request: Request, pk: int) -> Response:
        report = _visible_report(request, pk)
        if not services.can_delete(request.user, report):
            raise ReportNotEditable("只能删除自己的战报")
        # 删战报**不撤积分**：用户只定过「站主可撤销」，撤销一律由站主在后台做。
        # 去重键是「某人 + 某团」，所以删掉重写也不会二次发分。
        report.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class ReportAttachmentListView(APIView):
    """GET（看得见战报的人）/ POST（作者上传附件）/api/v1/reports/<pk>/attachments/"""

    def get_throttles(self):
        """上传档只加在 POST 上：GET 是公开读，套 30 次/小时的上传档会误伤游客。"""
        self.throttle_scope = "upload" if self.request.method == "POST" else None
        return super().get_throttles()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticatedAndActive()]
        return [AllowAny()]

    def get(self, request: Request, pk: int) -> Response:
        report = _visible_report(request, pk)
        serializer = ReportAttachmentSerializer(
            report.attachments.all(), many=True, context={"request": request}
        )
        return Response({"results": serializer.data})

    def post(self, request: Request, pk: int) -> Response:
        report = _visible_report(request, pk)
        if not services.can_edit(request.user, report):
            raise ReportNotEditable("只能给自己的战报传附件")
        serializer = AttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attachment = services.add_attachment(
            report, serializer.validated_data["file"], uploaded_by=request.user
        )
        return Response(
            ReportAttachmentSerializer(attachment, context={"request": request}).data,
            status=http_status.HTTP_201_CREATED,
        )


class ReportAttachmentDetailView(APIView):
    """DELETE /api/v1/reports/<pk>/attachments/<attachment_id>/ —— 作者删自己的附件。"""

    permission_classes = [IsAuthenticatedAndActive]

    def delete(self, request: Request, pk: int, attachment_id: int) -> Response:
        report = _visible_report(request, pk)
        if not services.can_edit(request.user, report):
            raise ReportNotEditable("只能删自己战报的附件")
        attachment = get_object_or_404(ReportAttachment, pk=attachment_id, report=report)
        services.delete_attachment(attachment)
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class AttachmentDownloadView(APIView):
    """GET /api/v1/reports/<pk>/attachments/<attachment_id>/download/ —— 受控下发。

    跟随战报可见性：看不见这份战报的人拿到 404，文件路径不可猜、也不经 Nginx 直出。
    """

    permission_classes = [AllowAny]

    def get(self, request: Request, pk: int, attachment_id: int):
        report = _visible_report(request, pk)
        attachment = get_object_or_404(ReportAttachment, pk=attachment_id, report=report)
        if not attachment.file:
            raise Http404
        return protected_file_response(attachment.file, download_name=attachment.original_name)


class ReportAbuseView(APIView):
    """POST /api/v1/reports/<pk>/report/ —— 举报一份战报，站主在后台处理。

    「用户举报入口首发只做照片与战报」。
    """

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request, pk: int) -> Response:
        report = _visible_report(request, pk)
        serializer = AbuseInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        abuse = services.report_abuse(
            request.user, report, reason=serializer.validated_data["reason"]
        )
        return Response(
            {"id": abuse.pk, "status": abuse.status, "created_at": abuse.created_at},
            status=http_status.HTTP_201_CREATED,
        )
