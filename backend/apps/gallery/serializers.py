"""相册序列化。"""

from __future__ import annotations

from django.urls import reverse
from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.gallery.models import (
    REASON_CHOICES,
    RESULT_DISMISSED,
    RESULT_RESTORED,
    RESULT_TAKEN_DOWN,
    Photo,
    PhotoReport,
)
from apps.gallery.services import can_moderate
from common.text import validate_no_bidi_controls


def _file_url(photo: Photo, size: str) -> str:
    """受控下发路径。绝不是 media 直链。"""
    return f"{reverse('v1:gallery:photo-file', kwargs={'pk': photo.pk})}?size={size}"


class PhotoSerializer(serializers.ModelSerializer):
    """一张照片对外的样子。"""

    uploader = PublicUserSerializer(read_only=True)
    game = serializers.IntegerField(source="game_id", read_only=True)
    game_title = serializers.CharField(source="game.title", read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    original_url = serializers.SerializerMethodField()
    taken_down_reason = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Photo
        fields = [
            "id",
            "game",
            "game_title",
            "uploader",
            "caption",
            "width",
            "height",
            "size",
            "status",
            "is_featured",
            "created_at",
            "thumbnail_url",
            "preview_url",
            "original_url",
            "taken_down_reason",
            "can_delete",
        ]
        read_only_fields = fields

    def get_thumbnail_url(self, obj: Photo) -> str:
        return _file_url(obj, "thumb")

    def get_preview_url(self, obj: Photo) -> str:
        return _file_url(obj, "preview")

    def get_original_url(self, obj: Photo) -> str:
        return _file_url(obj, "original")

    def get_taken_down_reason(self, obj: Photo) -> str:
        """下架/驳回理由只给上传者本人与站主看，不对普通浏览者解释别人的照片为什么没了。"""
        user = self._user()
        if user is None:
            return ""
        if obj.uploader_id == getattr(user, "pk", None) or can_moderate(user):
            return obj.taken_down_reason
        return ""

    def get_can_delete(self, obj: Photo) -> bool:
        user = self._user()
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return obj.uploader_id == user.pk or can_moderate(user)

    def _user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)


class PhotoUploadSerializer(serializers.Serializer):
    """上传入参。真正的校验（魔数、体积、像素、配额）在 services 里。"""

    # 故意用 FileField 而不是 ImageField：DRF 的 ImageField 会抢先用 Django 表单那套
    # 校验把非图片判成通用 validation_error，我们要的是 services 里那套
    # 「扩展名 + 魔数 + 像素上限」给出的 invalid_image / image_too_large 明确错误码。
    file = serializers.FileField(write_only=True)
    caption = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="",
        validators=[validate_no_bidi_controls],
    )


class PhotoReportCreateSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=REASON_CHOICES)
    reason_text = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )


class MyPhotoReportSerializer(serializers.ModelSerializer):
    """举报人视角：能看到自己举报的去向，但看不到处理人是谁。"""

    photo_id = serializers.IntegerField(source="photo.id", read_only=True)
    game_id = serializers.IntegerField(source="photo.game_id", read_only=True)
    photo_status = serializers.CharField(source="photo.status", read_only=True)
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)
    result_display = serializers.CharField(source="get_result_display", read_only=True)

    class Meta:
        model = PhotoReport
        fields = [
            "id",
            "photo_id",
            "game_id",
            "photo_status",
            "reason",
            "reason_display",
            "reason_text",
            "status",
            "result",
            "result_display",
            "result_note",
            "created_at",
            "handled_at",
        ]
        read_only_fields = fields


class ModerationReportSerializer(serializers.ModelSerializer):
    """站主视角：额外带举报人与照片摘要。**只挂在有审核权限位的接口上。**"""

    reporter = PublicUserSerializer(read_only=True)
    photo = PhotoSerializer(read_only=True)
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)

    class Meta:
        model = PhotoReport
        fields = [
            "id",
            "photo",
            "reporter",
            "reason",
            "reason_display",
            "reason_text",
            "status",
            "result",
            "result_note",
            "created_at",
            "handled_at",
        ]
        read_only_fields = fields


class HandleReportSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=[
            (RESULT_RESTORED, "恢复展示"),
            (RESULT_TAKEN_DOWN, "确认下架"),
            (RESULT_DISMISSED, "不予处理"),
        ]
    )
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class RejectPhotoSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
