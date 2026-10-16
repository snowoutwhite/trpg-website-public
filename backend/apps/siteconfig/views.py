"""站级配置的公开只读接口。"""

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.siteconfig.serializers import PublicSiteConfigSerializer
from apps.siteconfig.services import get_config


class PublicSiteConfigView(APIView):
    """GET /api/v1/siteconfig/ —— 游客可读，只返回非敏感字段。"""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        return Response(PublicSiteConfigSerializer(get_config()).data)
