"""战报序列化。"""

from __future__ import annotations

from django.urls import reverse
from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.games.models import Game
from apps.reports.models import (
    BODY_MAX_LENGTH,
    VISIBILITY_CHOICES,
    Report,
    ReportAttachment,
)
from common.text import validate_no_bidi_controls

# 列表里正文的截断长度：避免一页 20 条各拖着 50k 正文。
EXCERPT_LENGTH = 200


class ReportAttachmentSerializer(serializers.ModelSerializer):
    """附件元数据 + 鉴权下载路径。"""

    download_url = serializers.SerializerMethodField()

    class Meta:
        model = ReportAttachment
        fields = ["id", "original_name", "size", "mime", "download_url", "created_at"]
        read_only_fields = fields

    def get_download_url(self, obj: ReportAttachment) -> str:
        return reverse(
            "v1:reports:attachment-download",
            kwargs={"pk": obj.report_id, "attachment_id": obj.pk},
        )


class _GameBriefSerializer(serializers.ModelSerializer):
    """战报里带的团信息：只要标题与时间，不带名单。"""

    class Meta:
        model = Game
        fields = ["id", "title", "rule_system", "start_at", "finished_at"]
        read_only_fields = fields


class ReportListSerializer(serializers.ModelSerializer):
    """列表：正文只给摘要，附件只给数量。"""

    author = PublicUserSerializer(read_only=True)
    game = _GameBriefSerializer(read_only=True)
    excerpt = serializers.SerializerMethodField()
    attachment_count = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id",
            "game",
            "author",
            "title",
            "excerpt",
            "visibility",
            "is_featured",
            "attachment_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_excerpt(self, obj: Report) -> str:
        body = obj.body_markdown or ""
        return body[:EXCERPT_LENGTH]

    def get_attachment_count(self, obj: Report) -> int:
        # 用 all() 走 prefetch 缓存；count() 会绕过缓存、一页 20 条就是 20 次查询。
        return len(obj.attachments.all())


class ReportDetailSerializer(serializers.ModelSerializer):
    """详情：正文按原文回传，附件带鉴权下载路径。"""

    author = PublicUserSerializer(read_only=True)
    game = _GameBriefSerializer(read_only=True)
    attachments = ReportAttachmentSerializer(many=True, read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id",
            "game",
            "author",
            "title",
            "body_markdown",
            "visibility",
            "is_featured",
            "attachments",
            "can_edit",
            "can_delete",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_can_edit(self, obj: Report) -> bool:
        from apps.reports import services

        return services.can_edit(self._user(), obj)

    def get_can_delete(self, obj: Report) -> bool:
        from apps.reports import services

        return services.can_delete(self._user(), obj)


class ReportCreateSerializer(serializers.Serializer):
    """提交战报（新建或更新本人在该团的那一份）。"""

    game = serializers.PrimaryKeyRelatedField(queryset=Game.objects.all())
    title = serializers.CharField(max_length=80, validators=[validate_no_bidi_controls])
    body_markdown = serializers.CharField(
        max_length=BODY_MAX_LENGTH, allow_blank=True, required=False, default=""
    )
    visibility = serializers.ChoiceField(choices=VISIBILITY_CHOICES, required=False)

    def validate_title(self, value: str) -> str:
        title = value.strip()
        if not title:
            raise serializers.ValidationError("战报标题不能为空")
        return title


class ReportUpdateSerializer(serializers.Serializer):
    """改自己的战报。`game` 与 `is_featured` 都不可改（换团 = 另一份战报；精选只有站主能动）。"""

    title = serializers.CharField(
        max_length=80, required=False, validators=[validate_no_bidi_controls]
    )
    body_markdown = serializers.CharField(
        max_length=BODY_MAX_LENGTH, allow_blank=True, required=False
    )
    visibility = serializers.ChoiceField(choices=VISIBILITY_CHOICES, required=False)

    def validate_title(self, value: str) -> str:
        title = value.strip()
        if not title:
            raise serializers.ValidationError("战报标题不能为空")
        return title


class ImportTargetSerializer(serializers.Serializer):
    """从文档导入正文的第一步：只取 `game` 判资格（与写战报同一口径）。"""

    game = serializers.PrimaryKeyRelatedField(queryset=Game.objects.all())


class DocumentImportSerializer(ImportTargetSerializer):
    """第二步：`file` 是 .docx / .txt；格式与安全校验在 `importing.py`。"""

    file = serializers.FileField()


class AttachmentUploadSerializer(serializers.Serializer):
    """上传附件。白名单 / 大小 / 魔数校验在 services 层（复用角色卡那一套）。"""

    file = serializers.FileField()


class AbuseInputSerializer(serializers.Serializer):
    """举报战报，理由必填。"""

    reason = serializers.CharField(max_length=1000)

    def validate_reason(self, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise serializers.ValidationError("请填写举报理由。")
        return reason
