"""玩家卡 / GM 卡序列化。

隐私约定：公开序列化器里绝不出现邮箱、评价人身份、原始评价内容。
**被评次数未达公布阈值时，`likes` / `dislikes` / `reviews_received` 三个计数一律回 null**
（本人卡与公开卡同一口径，见 `_MaskedCountsMixin`）；达阈值后才同时给出档位与数字。
计数本身也只统计「已过延迟、对被评者已可见」的评价，由 `reviews.services.review_counts` 负责。
"""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.profiles.models import GMCard, PlayerCard
from apps.siteconfig.services import get_config


class _MaskedCountsMixin(serializers.ModelSerializer):
    """被评次数未达公布阈值时，三个计数一律回 null。

    三个字段绑在一起（W5）：
    - `likes` / `dislikes` 单独露出去就能手算比例，绕过公布阈值；
    - `reviews_received` 单独露出去更糟 —— 它是**实时跳动**的，游客只要轮询
      任意用户的个人空间，就能看着数字 +1，从而测出「此刻有人评了他」，
      把匿名评价的提交时刻交给第三方（W3 红队复现，`test_公开个人空间不应实时暴露被评次数`）。
      统计侧已经只计「已过延迟」的评价（`reviews.services.review_counts`），
      这里再加一道阈值闸，本人卡与公开卡用同一份判断。
    """

    level_display = serializers.CharField(read_only=True)
    likes = serializers.SerializerMethodField()
    dislikes = serializers.SerializerMethodField()
    reviews_received = serializers.SerializerMethodField()

    def _published(self, obj) -> bool:
        config = get_config()
        if not config.like_feature_enabled:
            # 站主关掉赞功能时入口隐藏、门槛失效，数字同样不外露。
            return False
        return obj.reviews_received >= config.like_level_publish_threshold

    def get_likes(self, obj) -> int | None:
        return obj.likes if self._published(obj) else None

    def get_dislikes(self, obj) -> int | None:
        return obj.dislikes if self._published(obj) else None

    def get_reviews_received(self, obj) -> int | None:
        return obj.reviews_received if self._published(obj) else None


class _PublicCardMixin(_MaskedCountsMixin):
    """公开卡：字段与本人卡一致，隐私闸也一致（第 6 节第 4 条）。"""


class PublicPlayerCardSerializer(_PublicCardMixin):
    class Meta:
        model = PlayerCard
        fields = [
            "taboos",
            "preferred_rule_systems",
            "free_text",
            "games_played",
            "reviews_received",
            "likes",
            "dislikes",
            "level",
            "level_display",
        ]
        read_only_fields = fields


class PublicGMCardSerializer(_PublicCardMixin):
    class Meta:
        model = GMCard
        fields = [
            "style_text",
            "games_hosted",
            "reviews_received",
            "likes",
            "dislikes",
            "level",
            "level_display",
        ]
        read_only_fields = fields


# 长文本的安全上限（不是产品意义上的「字数限制」，而是防止单账号往库里灌几十 MB）。
# 雷点 / 自由文本 / GM 风格都是 TextField，DRF 默认不限长，20000 字远超任何合理自我介绍。
LONG_TEXT_MAX_LENGTH = 20_000


class MyPlayerCardSerializer(_MaskedCountsMixin):
    taboos = serializers.CharField(
        required=False, allow_blank=True, max_length=LONG_TEXT_MAX_LENGTH
    )
    free_text = serializers.CharField(
        required=False, allow_blank=True, max_length=LONG_TEXT_MAX_LENGTH
    )

    class Meta:
        model = PlayerCard
        fields = [
            "taboos",
            "preferred_rule_systems",
            "free_text",
            "games_played",
            "reviews_received",
            "likes",
            "dislikes",
            "level",
            "level_display",
        ]
        read_only_fields = ["games_played", "reviews_received", "likes", "dislikes", "level", "level_display"]

    def validate_preferred_rule_systems(self, value):
        return _clean_rule_systems(value)


class MyGMCardSerializer(_MaskedCountsMixin):
    style_text = serializers.CharField(
        required=False, allow_blank=True, max_length=LONG_TEXT_MAX_LENGTH
    )

    class Meta:
        model = GMCard
        fields = [
            "style_text",
            "games_hosted",
            "reviews_received",
            "likes",
            "dislikes",
            "level",
            "level_display",
        ]
        read_only_fields = ["games_hosted", "reviews_received", "likes", "dislikes", "level", "level_display"]


class PublicProfileSerializer(serializers.Serializer):
    """个人空间：公开可见的全部内容，绝不含邮箱。"""

    user = PublicUserSerializer(read_only=True)
    player_card = PublicPlayerCardSerializer(read_only=True)
    gm_card = PublicGMCardSerializer(read_only=True, allow_null=True)


def _clean_rule_systems(value) -> list[str]:
    if not isinstance(value, list):
        raise serializers.ValidationError("必须是字符串数组")
    cleaned = []
    for item in value:
        if not isinstance(item, str):
            raise serializers.ValidationError("必须是字符串数组")
        text = item.strip()
        if text and text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > 20:
        raise serializers.ValidationError("偏好规则最多 20 项")
    return cleaned
