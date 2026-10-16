"""团的序列化。"""

from __future__ import annotations

import re
import unicodedata

from django.urls import reverse
from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.games.models import (
    GAME_RECRUITING,
    SIGNUP_WITHDRAWN,
    Game,
    Session,
    Signup,
    Tag,
)
from apps.profiles.levels import LEVEL_LABELS
from apps.profiles.serializers import LONG_TEXT_MAX_LENGTH
from common.text import validate_no_bidi_controls

# 标签名归一化（与 `apps.accounts.validators.normalize_nickname` 同一套思路）：
# 标签是全站共享、按名字 `get_or_create` 的公共命名空间，不归一化就能用全角、
# 零宽空格、RTL override 造出肉眼同名的两枚标签（architecture 第 6 节第 6 条）。
TAG_MAX_LENGTH = 30
_TAG_FORBIDDEN_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn"}
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_tag_name(raw: str) -> str:
    """NFKC + 折叠空白 + 拒绝不可见字符；返回空串表示「这个标签可以丢掉」。"""
    text = unicodedata.normalize("NFKC", raw or "")
    text = _WHITESPACE_RUN.sub(" ", text).strip()
    if not text:
        return ""
    if any(unicodedata.category(ch) in _TAG_FORBIDDEN_CATEGORIES for ch in text):
        raise serializers.ValidationError("标签不能包含不可见字符或控制字符")
    if len(text) > TAG_MAX_LENGTH:
        raise serializers.ValidationError(f"标签最长 {TAG_MAX_LENGTH} 个字符")
    return text


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "is_preset"]
        read_only_fields = fields


class SessionSerializer(serializers.ModelSerializer):
    display_label = serializers.CharField(read_only=True)

    class Meta:
        model = Session
        fields = ["id", "index", "label", "display_label", "held_at"]
        read_only_fields = ["id", "display_label"]


class _SignupCardSerializer(serializers.Serializer):
    """交上来的卡：只给 GM 看，且只给鉴权下载路径。"""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    rule_system = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    download_url = serializers.SerializerMethodField()

    def get_download_url(self, obj) -> str:
        return reverse("v1:charactercards:card-download", kwargs={"pk": obj.pk})


class RecruitingSignupSerializer(serializers.ModelSerializer):
    """招募中名单（登录用户可见）：昵称、头像、报名顺序。"""

    player = PublicUserSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Signup
        fields = ["id", "order", "player", "status", "status_display", "created_at"]
        read_only_fields = fields


class RosterSignupSerializer(RecruitingSignupSerializer):
    """正式名单（只给同团：GM + accepted 者）。不含卡，不含审批备注。"""

    class Meta(RecruitingSignupSerializer.Meta):
        fields = [*RecruitingSignupSerializer.Meta.fields, "attended"]
        read_only_fields = fields


class GMSignupSerializer(serializers.ModelSerializer):
    """GM 面板名单：全部状态 + 卡信息 + 审批备注 + 退出申请。"""

    player = PublicUserSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    card = _SignupCardSerializer(read_only=True)

    class Meta:
        model = Signup
        fields = [
            "id",
            "order",
            "player",
            "status",
            "status_display",
            "card",
            "card_uploaded_by_gm",
            "card_submitted_at",
            "review_note",
            "withdraw_requested_at",
            "withdraw_reason",
            "attended",
            "created_at",
        ]
        read_only_fields = fields


class MySignupSerializer(serializers.ModelSerializer):
    """我的报名：给本人看自己的那一条，附团的摘要。"""

    game = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    card = _SignupCardSerializer(read_only=True)

    class Meta:
        model = Signup
        fields = [
            "id",
            "game",
            "order",
            "status",
            "status_display",
            "card",
            "card_uploaded_by_gm",
            "card_submitted_at",
            "review_note",
            "withdraw_requested_at",
            "attended",
            "created_at",
        ]
        read_only_fields = fields

    def get_game(self, obj: Signup) -> dict:
        game = obj.game
        return {
            "id": game.pk,
            "title": game.title,
            "status": game.status,
            "status_display": game.get_status_display(),
            "start_at": game.start_at,
            "card_deadline": game.card_deadline,
            "requires_card": game.requires_card,
            "signup_mode": game.signup_mode,
        }


class GameListSerializer(serializers.ModelSerializer):
    """招募列表：游客可读，只有公告层面的信息。"""

    gm = PublicUserSerializer(read_only=True)
    tags = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    mode_display = serializers.CharField(source="get_mode_display", read_only=True)
    signup_mode_display = serializers.CharField(source="get_signup_mode_display", read_only=True)
    min_level_display = serializers.SerializerMethodField()
    occupied_seats = serializers.IntegerField(read_only=True)
    accepted_count = serializers.IntegerField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)

    class Meta:
        model = Game
        fields = [
            "id",
            "gm",
            "title",
            "rule_system",
            "start_at",
            "mode",
            "mode_display",
            "location",
            "tags",
            "min_players",
            "max_players",
            "signup_mode",
            "signup_mode_display",
            "min_play_count",
            "min_level",
            "min_level_display",
            "requires_card",
            "card_deadline",
            "status",
            "status_display",
            "occupied_seats",
            "accepted_count",
            "is_full",
            "created_at",
        ]
        read_only_fields = fields

    def get_min_level_display(self, obj: Game) -> str:
        return LEVEL_LABELS.get(obj.min_level, "")


class GameDetailSerializer(GameListSerializer):
    """团详情：公告全文 + 右侧 GM 面板（昵称头像 + GM 卡公开统计）。

    GM 面板用 profiles 的公开序列化器，档位未公布时连赞/倒赞绝对值都不外露。
    """

    gm_card = serializers.SerializerMethodField()
    campaign_prev = serializers.SerializerMethodField()
    sessions = SessionSerializer(many=True, read_only=True)
    my_signup = serializers.SerializerMethodField()
    can_signup = serializers.SerializerMethodField()
    review_window_ends_at = serializers.SerializerMethodField()

    class Meta(GameListSerializer.Meta):
        fields = [
            *GameListSerializer.Meta.fields,
            "announcement",
            "requirements",
            "mutual_review",
            "campaign_prev",
            "restrict_to_prev_members",
            "cancel_reason",
            "finished_at",
            "gm_card",
            "sessions",
            "my_signup",
            "can_signup",
            "review_window_ends_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_gm_card(self, obj: Game):
        from apps.profiles.serializers import PublicGMCardSerializer
        from apps.profiles.services import ensure_gm_card

        if not obj.gm.is_gm:
            return None
        return PublicGMCardSerializer(ensure_gm_card(obj.gm)).data

    def get_review_window_ends_at(self, obj: Game):
        """评价窗口截止时刻 = 结团时间 + 站点配置的评价窗口天数；没结团就是 null。

        天数是站级可配项，前端不该自己拿 `finished_at` 再去算一遍
        （算错了就会在「还能评」和「已冻结」之间给出与后端相反的提示）。
        """
        from apps.reviews.services import window_ends_at

        return window_ends_at(obj)

    def get_campaign_prev(self, obj: Game):
        if obj.campaign_prev_id is None:
            return None
        return {"id": obj.campaign_prev_id, "title": obj.campaign_prev.title}

    def _me(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return user if getattr(user, "is_authenticated", False) else None

    def get_my_signup(self, obj: Game):
        user = self._me()
        if user is None:
            return None
        record = obj.signups.filter(player=user).select_related("card").first()
        return MySignupSerializer(record).data if record else None

    def get_can_signup(self, obj: Game) -> bool:
        user = self._me()
        if user is None or obj.gm_id == user.pk:
            return False
        if obj.status != GAME_RECRUITING or obj.is_full:
            return False
        return not obj.signups.filter(player=user).exclude(status=SIGNUP_WITHDRAWN).exists()


class GameWriteSerializer(serializers.ModelSerializer):
    """放团 / 改团的入参。真正的规则（人数范围、截止不得晚于开团）在 services 里校验。"""

    tags = serializers.ListField(
        child=serializers.CharField(max_length=TAG_MAX_LENGTH), required=False, allow_empty=True
    )
    card_deadline = serializers.DateTimeField(required=False, allow_null=True)
    # TextField + DRF 默认不限长 = 一个账号就能往库里灌几十 MB（architecture 第 6 节第 7 条）。
    announcement = serializers.CharField(
        required=False, allow_blank=True, max_length=LONG_TEXT_MAX_LENGTH
    )
    requirements = serializers.CharField(
        required=False, allow_blank=True, max_length=LONG_TEXT_MAX_LENGTH
    )

    class Meta:
        model = Game
        fields = [
            "title",
            "announcement",
            "rule_system",
            "start_at",
            "mode",
            "location",
            "requirements",
            "tags",
            "min_players",
            "max_players",
            "signup_mode",
            "min_play_count",
            "min_level",
            "requires_card",
            "card_deadline",
            "mutual_review",
            "campaign_prev",
            "restrict_to_prev_members",
        ]
        extra_kwargs = {"title": {"validators": [validate_no_bidi_controls]}}

    def validate_title(self, value: str) -> str:
        title = value.strip()
        if not title:
            raise serializers.ValidationError("标题不能为空。")
        return title

    def validate_campaign_prev(self, value):
        """战役后续团只能指向自己开过的团，避免蹭别人的团限制报名。"""
        if value is None:
            return value
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or value.gm_id != user.pk:
            raise serializers.ValidationError("前一个团必须是你自己开的团。")
        return value

    def validate_tags(self, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            name = normalize_tag_name(item)
            if name and name not in cleaned:
                cleaned.append(name)
        if len(cleaned) > 10:
            raise serializers.ValidationError("一个团最多 10 个标签")
        return cleaned


# --------------------------------------------------------------------------
# 动作入参
# --------------------------------------------------------------------------


class SubmitCardInputSerializer(serializers.Serializer):
    card_id = serializers.IntegerField()


class WithdrawInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ReviewInputSerializer(serializers.Serializer):
    approved = serializers.BooleanField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ReasonInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class ConfirmWithdrawInputSerializer(serializers.Serializer):
    approved = serializers.BooleanField(default=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ExpandInputSerializer(serializers.Serializer):
    max_players = serializers.IntegerField(min_value=1)


class FinishInputSerializer(serializers.Serializer):
    """结团必须交到场名单；空数组表示无人到场。"""

    attended_signup_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True
    )


class GMUploadCardInputSerializer(serializers.Serializer):
    file = serializers.FileField()
    name = serializers.CharField(
        max_length=60, required=False, allow_blank=True, default="",
        validators=[validate_no_bidi_controls],
    )
    rule_system = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
