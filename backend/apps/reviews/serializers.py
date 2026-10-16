"""团后评价序列化。"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.games.models import Game
from apps.reviews.models import ROLE_CHOICES, VERDICT_CHOICES, Review
from apps.reviews.services import REVIEW_TEXT_MAX_LENGTH

_VERDICT_LABELS = dict(VERDICT_CHOICES)
_ROLE_LABELS = dict(ROLE_CHOICES)


class ReviewGameSerializer(serializers.ModelSerializer):
    """评价里附带的团信息：只有标题与日期，没有名单。"""

    class Meta:
        model = Game
        fields = ["id", "title", "start_at", "finished_at"]
        read_only_fields = fields


class AnonymousReviewSerializer(serializers.Serializer):
    """被评者 / 互见面板看到的评价。白名单四项，多一个字段都要先过匿名审查。"""

    verdict = serializers.CharField(read_only=True)
    verdict_display = serializers.SerializerMethodField()
    text = serializers.CharField(read_only=True)
    reviewee_role = serializers.CharField(read_only=True)
    game = ReviewGameSerializer(read_only=True)

    def get_verdict_display(self, obj: Review) -> str:
        return _VERDICT_LABELS.get(obj.verdict, "")


class GivenReviewSerializer(serializers.Serializer):
    """本人回顾自己发出的评价。"""

    id = serializers.IntegerField(read_only=True)
    game = ReviewGameSerializer(read_only=True)
    reviewee = PublicUserSerializer(read_only=True)
    reviewee_role = serializers.CharField(read_only=True)
    verdict = serializers.CharField(read_only=True)
    verdict_display = serializers.SerializerMethodField()
    text = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def get_verdict_display(self, obj: Review) -> str:
        return _VERDICT_LABELS.get(obj.verdict, "")


class PendingTargetSerializer(serializers.Serializer):
    """待评对象：某个团里还没被本人评过的人。"""

    user = PublicUserSerializer(read_only=True)
    role = serializers.CharField(read_only=True)
    role_display = serializers.SerializerMethodField()

    def get_role_display(self, obj: dict) -> str:
        return _ROLE_LABELS.get(obj.get("role"), "")


class PendingGameSerializer(serializers.Serializer):
    game = ReviewGameSerializer(read_only=True)
    window_ends_at = serializers.DateTimeField(read_only=True)
    targets = PendingTargetSerializer(many=True, read_only=True)


class MutualGroupSerializer(serializers.Serializer):
    """互见面板的一组：某位到场成员收到的评价。"""

    user = PublicUserSerializer(read_only=True)
    role = serializers.CharField(read_only=True)
    reviews = AnonymousReviewSerializer(many=True, read_only=True)


class ReviewWriteSerializer(serializers.Serializer):
    """提交/修改评价的入参。赞与倒赞都必须附文字。"""

    game = serializers.PrimaryKeyRelatedField(queryset=Game.objects.all())
    reviewee = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all())
    verdict = serializers.ChoiceField(choices=VERDICT_CHOICES)
    text = serializers.CharField(
        max_length=REVIEW_TEXT_MAX_LENGTH,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={"blank": "点赞或倒赞均须填写评价内容；如不填写，请勿提交，可选择「无评价」。"},
    )

    def validate_text(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("点赞或倒赞均须填写评价内容；如不填写，请勿提交，可选择「无评价」。")
        return cleaned
