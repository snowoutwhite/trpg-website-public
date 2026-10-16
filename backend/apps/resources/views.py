"""资源区接口。"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.resources import services
from apps.resources.permissions import ReadOnlyOrCanUpload, ReadOnlyOrIsUploaderOrApprover
from apps.resources.serializers import ResourceSerializer, ResourceWriteSerializer
from common.exceptions import ApiError
from common.files import protected_file_response
from common.permissions import IsAuthenticatedAndActive


class ResourceListCreateView(ListCreateAPIView):
    """GET /api/v1/resources/ —— 游客可读，只列已审核（自己的投稿与审核者除外）。
    POST /api/v1/resources/ —— 上传，需要 `resources.add_resource` 权限位。
    """

    permission_classes = [ReadOnlyOrCanUpload]

    @property
    def throttle_scope(self) -> str | None:
        """只给上传限速；游客浏览列表不该吃 upload 档。"""
        return "upload" if self.request.method == "POST" else None

    def get_queryset(self):
        queryset = services.visible_resources(self.request.user)
        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)
        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        return queryset

    def get_serializer_class(self):
        return ResourceWriteSerializer if self.request.method == "POST" else ResourceSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = ResourceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resource = services.create_resource(uploader=request.user, **serializer.validated_data)
        return Response(ResourceSerializer(resource).data, status=status.HTTP_201_CREATED)


class ResourceDetailView(RetrieveUpdateDestroyAPIView):
    """GET 游客可读；PATCH/DELETE 仅上传者本人或有审核权限者。"""

    permission_classes = [ReadOnlyOrIsUploaderOrApprover]

    def get_queryset(self):
        return services.visible_resources(self.request.user)

    def get_serializer_class(self):
        return ResourceSerializer if self.request.method in ("GET", "HEAD") else ResourceWriteSerializer

    def update(self, request: Request, *args, **kwargs) -> Response:
        resource = self.get_object()
        serializer = ResourceWriteSerializer(resource, data=request.data, partial=kwargs.pop("partial", False))
        serializer.is_valid(raise_exception=True)
        resource = services.update_resource(resource, editor=request.user, **serializer.validated_data)
        return Response(ResourceSerializer(resource).data)


class ResourceCategoryListView(APIView):
    """GET /api/v1/resources/categories/ —— 已审核资源的分类清单（去重计数）。

    游客可读，口径与资源列表一致。
    不分页：分类是个位数量级的枚举，前端一次性拿去渲染筛选条。
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        return Response({"results": services.approved_categories()})


class ResourceDownloadView(APIView):
    """GET /api/v1/resources/<id>/download/ —— 登录用户下载，走鉴权视图而不是直出目录。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request, pk: int):
        # 先按「能不能看见」取，看不见的一律 404，不用 403 暴露未审核条目的存在。
        resource = get_object_or_404(services.visible_resources(request.user), pk=pk)
        if not services.can_download(request.user, resource):
            raise PermissionDenied("你没有权限下载这一条资源。")
        if not resource.is_file or not resource.file:
            raise ApiError("这条是外部链接，没有可下载的文件，请点击链接前往原站查看。", code="not_a_file_resource")
        return protected_file_response(resource.file, download_name=services.download_filename(resource))
