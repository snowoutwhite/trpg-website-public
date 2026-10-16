"""角色卡序列化。"""

from __future__ import annotations

from django.urls import reverse
from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.charactercards import services
from apps.charactercards.models import CharacterCard, CharacterCardFile
from common.text import validate_no_bidi_controls


class CardFileSerializer(serializers.ModelSerializer):
    """文件版本的元数据。只有卡主（及 games 阶段获准的人）看得到。"""

    uploaded_by = PublicUserSerializer(read_only=True)

    class Meta:
        model = CharacterCardFile
        fields = [
            "id",
            "version",
            "original_name",
            "size",
            "mime",
            "uploaded_by",
            "uploaded_by_gm",
            "created_at",
        ]
        read_only_fields = fields


class _CardBaseSerializer(serializers.ModelSerializer):
    owner = PublicUserSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    games_played = serializers.SerializerMethodField()
    has_file = serializers.BooleanField(read_only=True)
    is_usable_for_signup = serializers.BooleanField(read_only=True)
    can_download = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    def get_games_played(self, obj: CharacterCard) -> list:
        """参与过的团；games 尚未实现时为空列表。"""
        return services.games_played_for(obj)

    def _request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_can_download(self, obj: CharacterCard) -> bool:
        return bool(obj.has_file and services.can_view_file(self._request_user(), obj))

    def get_download_url(self, obj: CharacterCard) -> str | None:
        if not self.get_can_download(obj):
            return None
        return reverse("v1:charactercards:card-download", kwargs={"pk": obj.pk})


class PublicCardSerializer(_CardBaseSerializer):
    """卡池与他人视角：只露名称、规则、次数、跑过的团。"""

    class Meta:
        model = CharacterCard
        fields = [
            "id",
            "owner",
            "name",
            "rule_system",
            "status",
            "status_display",
            "play_count",
            "games_played",
            "is_public",
            "is_usable_for_signup",
            "has_file",
            "can_download",
            "download_url",
            "created_at",
        ]
        read_only_fields = fields


class MyCardSerializer(_CardBaseSerializer):
    """自己的卡：多一个备注，且名称 / 规则 / 公开 / 状态可改。"""

    class Meta:
        model = CharacterCard
        fields = [
            "id",
            "owner",
            "name",
            "rule_system",
            "note",
            "status",
            "status_display",
            "is_public",
            "play_count",
            "games_played",
            "is_usable_for_signup",
            "has_file",
            "can_download",
            "download_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "owner",
            "status_display",
            "play_count",
            "games_played",
            "is_usable_for_signup",
            "has_file",
            "can_download",
            "download_url",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"name": {"validators": [validate_no_bidi_controls]}}

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("请为这张卡填写名称。")
        return name

    def validate_rule_system(self, value: str) -> str:
        """规则可选站点预设，也可自定义文本（需求整理第 7 节 + 玩家卡同款口径）。"""
        return value.strip()


class CardFileUploadSerializer(serializers.Serializer):
    """上传新版本文件。真正的格式/大小/魔数校验在 services 层做。"""

    file = serializers.FileField()
