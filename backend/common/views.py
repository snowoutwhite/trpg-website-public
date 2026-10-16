"""全站级别的零散视图。"""

from django.http import Http404, HttpRequest
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response


def deny_protected_media(request: HttpRequest, *args, **kwargs):
    """开发期 Django 直出 MEDIA_ROOT 时，把 protected/ 子目录一口回绝。

    受保护文件（私密角色卡、待审照片、战报附件）只能经鉴权视图 +
    `common.files.protected_file_response` 下发；生产由 Nginx 的 internal location
    保证这一点，开发期则靠本视图堵住 `static()` 留下的口子。
    """
    raise Http404("受保护文件不能直接访问")


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """健康检查：容器编排与 Nginx 探活用，不返回任何内部细节。"""
    return Response({"status": "ok"})
