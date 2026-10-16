"""资源区序列化。

隐私/安全约定：
- 上传者一律用 `PublicUserSerializer`（id / nickname / avatar / is_gm），绝不出现邮箱。
- **绝不回传 `file.url`**：资源文件放在受保护目录，直出 URL 会让目录可枚举；
  对外只给 `download_url`（鉴权视图的路径）。
"""

from __future__ import annotations

from django.urls import reverse
from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.resources import services
from apps.resources.models import Resource, ResourceKind, http_url_validator
from common.text import validate_no_bidi_controls


class ResourceSerializer(serializers.ModelSerializer):
    """对外读表示。"""

    uploader = PublicUserSerializer(read_only=True)
    download_url = serializers.SerializerMethodField()
    file_extension = serializers.SerializerMethodField()

    class Meta:
        model = Resource
        fields = [
            "id",
            "title",
            "description",
            "kind",
            "category",
            "url",
            "download_url",
            "file_extension",
            "uploader",
            "is_approved",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_download_url(self, obj: Resource) -> str | None:
        if not obj.is_file or not obj.file:
            return None
        return reverse("v1:resources:download", kwargs={"pk": obj.pk})

    def get_file_extension(self, obj: Resource) -> str:
        if not obj.is_file or not obj.file:
            return ""
        _, _, suffix = obj.file.name.rpartition(".")
        return suffix.lower() if suffix else ""


class ResourceWriteSerializer(serializers.ModelSerializer):
    """上传 / 修改的入参。`is_approved` 不接受前端传值，由 services 按权限位决定。"""

    url = serializers.URLField(
        max_length=500, required=False, allow_blank=True, validators=[http_url_validator]
    )

    class Meta:
        model = Resource
        fields = ["title", "description", "kind", "file", "url", "category"]
        extra_kwargs = {"title": {"validators": [validate_no_bidi_controls]}}

    def validate_file(self, value):
        if value is not None:
            services.assert_extension_allowed(getattr(value, "name", ""))
        return value

    def validate(self, attrs):
        """kind 与 file/url 必须自洽；PATCH 时要看合并后的状态。"""
        kind = attrs.get("kind") or getattr(self.instance, "kind", ResourceKind.FILE)
        has_file = bool(attrs.get("file") or (self.instance.file if self.instance else None))
        has_url = bool(attrs.get("url") or (self.instance.url if self.instance else ""))
        # 本次请求显式把某一侧清空时，以请求为准。
        if "file" in attrs:
            has_file = bool(attrs["file"])
        if "url" in attrs:
            has_url = bool(attrs["url"])

        if kind == ResourceKind.FILE and not has_file:
            raise serializers.ValidationError({"file": ["文件类资源必须上传文件"]})
        if kind == ResourceKind.LINK and not has_url:
            raise serializers.ValidationError({"url": ["链接类资源必须填 http/https 外链"]})
        return attrs
