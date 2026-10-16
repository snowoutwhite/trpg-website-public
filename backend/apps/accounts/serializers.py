"""账号域序列化。"""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import GMApplication, User
from apps.accounts.services import nickname_change_available_at


class PublicUserSerializer(serializers.ModelSerializer):
    """对外公开的用户表示：任何第三方可见的字段都必须在这里列全。"""

    avatar = serializers.ImageField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "nickname", "avatar", "is_gm"]
        read_only_fields = fields


class MeSerializer(serializers.ModelSerializer):
    """仅本人可见。唯一会返回邮箱的序列化器。"""

    email_verified = serializers.SerializerMethodField()
    nickname_change_available_at = serializers.SerializerMethodField()
    has_pending_gm_application = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "email_verified",
            "nickname",
            "avatar",
            "is_gm",
            "is_staff",
            "is_banned",
            "is_muted",
            "is_deactivated",
            "date_joined",
            "nickname_change_available_at",
            "has_pending_gm_application",
        ]
        read_only_fields = [
            "id",
            "email",
            "email_verified",
            "avatar",
            "is_gm",
            "is_staff",
            "is_banned",
            "is_muted",
            "is_deactivated",
            "date_joined",
            "nickname_change_available_at",
            "has_pending_gm_application",
        ]

    def get_email_verified(self, obj: User) -> bool:
        from allauth.account.models import EmailAddress

        return EmailAddress.objects.filter(user=obj, verified=True).exists()

    def get_nickname_change_available_at(self, obj: User):
        return nickname_change_available_at(obj)

    def get_has_pending_gm_application(self, obj: User) -> bool:
        return GMApplication.objects.filter(
            applicant=obj, status=GMApplication.STATUS_PENDING
        ).exists()


class NicknameInputSerializer(serializers.Serializer):
    nickname = serializers.CharField(max_length=24)


class AvatarInputSerializer(serializers.Serializer):
    avatar = serializers.ImageField()


class GMApplicationInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)


class GMApplicationSerializer(serializers.ModelSerializer):
    """只返回给申请人本人；不暴露审批人身份。"""

    class Meta:
        model = GMApplication
        fields = ["id", "reason", "status", "review_note", "created_at", "reviewed_at"]
        read_only_fields = fields
