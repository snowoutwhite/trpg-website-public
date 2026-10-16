"""通知序列化。只服务本人，actor 只露公开字段。"""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.notifications import events
from apps.notifications.models import EmailPreference, Notification


class NotificationSerializer(serializers.ModelSerializer):
    actor = PublicUserSerializer(read_only=True)
    title = serializers.CharField(read_only=True)
    target_type = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "event",
            "title",
            "actor",
            "target_type",
            "target_object_id",
            "payload",
            "created_at",
            "read_at",
        ]
        read_only_fields = fields

    def get_target_type(self, obj: Notification) -> str | None:
        if obj.target_content_type_id is None:
            return None
        return obj.target_content_type.model


class EmailPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailPreference
        fields = ["email_enabled", "per_event"]

    def validate_per_event(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("必须是对象")
        unknown = set(value) - set(events.ALL_EVENTS)
        if unknown:
            raise serializers.ValidationError(f"未知事件：{', '.join(sorted(unknown))}")
        return {k: bool(v) for k, v in value.items()}


# 一次最多能标多少条已读。不封顶的话，一个请求就能拼出上万个绑定变量的 IN 查询，
# SQLite 直接抛 "too many SQL variables"（500），Postgres 则是一次超长扫描。
MARK_READ_MAX_IDS = 500


class MarkReadInputSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        max_length=MARK_READ_MAX_IDS,
    )
