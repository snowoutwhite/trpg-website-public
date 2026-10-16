"""术语表 / 新人指南 / FAQ 的只读公开接口（游客可见）。"""

from __future__ import annotations

from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny

from apps.content.models import FAQ, GlossaryTerm, Guide
from apps.content.serializers import (
    FAQSerializer,
    GlossaryTermSerializer,
    GuideDetailSerializer,
    GuideListSerializer,
)


class _PublicListView(ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []


class GlossaryListView(_PublicListView):
    serializer_class = GlossaryTermSerializer
    queryset = GlossaryTerm.objects.published()
    pagination_class = None  # 术语表一次给全，前端本地搜索


class GuideListView(_PublicListView):
    serializer_class = GuideListSerializer
    queryset = Guide.objects.published()
    pagination_class = None


class GuideDetailView(RetrieveAPIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = GuideDetailSerializer
    queryset = Guide.objects.published()
    lookup_field = "slug"


class FAQListView(_PublicListView):
    serializer_class = FAQSerializer
    queryset = FAQ.objects.published()
    pagination_class = None
