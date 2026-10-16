"""玩家卡与 GM 卡。"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.profiles.levels import LEVEL_CHOICES
from common.models import TimeStampedModel


class BaseCard(TimeStampedModel):
    """玩家卡与 GM 卡共有的统计部分。"""

    reviews_received = models.PositiveIntegerField("被评次数", default=0)
    likes = models.PositiveIntegerField("赞数", default=0)
    dislikes = models.PositiveIntegerField("倒赞数", default=0)
    level = models.CharField(
        "赞级别档位", max_length=32, choices=LEVEL_CHOICES, blank=True, default="",
        help_text="评价数不足公布阈值时为空",
    )

    class Meta:
        abstract = True

    @property
    def level_display(self) -> str:
        from apps.profiles.levels import LEVEL_LABELS

        return LEVEL_LABELS.get(self.level, "")


class PlayerCard(BaseCard):
    """注册即有，承载 PL 侧的雷点、偏好规则、自由文本与统计。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="player_card"
    )
    taboos = models.TextField("雷点", blank=True, default="", help_text="本人不接受的题材或行为")
    preferred_rule_systems = models.JSONField(
        "偏好规则", default=list, blank=True,
        help_text="字符串数组；可多选站点预设，也可自定义",
    )
    free_text = models.TextField(
        "自由文本区", blank=True, default="",
        help_text="自我介绍、个人风格、跑团经验、接下来的想法等，非键值字段",
    )
    games_played = models.PositiveIntegerField("参团次数", default=0)

    class Meta:
        verbose_name = "玩家卡"
        verbose_name_plural = "玩家卡"

    def __str__(self) -> str:
        return f"玩家卡 · {self.user.nickname}"


class GMCard(BaseCard):
    """获得 GM 身份后出现，承载 GM 侧的风格文本与统计。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="gm_card"
    )
    games_hosted = models.PositiveIntegerField("主持团次数", default=0)
    style_text = models.TextField(
        "GM 风格与爱好", blank=True, default="",
        help_text="喜欢开的团与喜欢跑的团可以不同，单独写",
    )

    class Meta:
        verbose_name = "GM 卡"
        verbose_name_plural = "GM 卡"

    def __str__(self) -> str:
        return f"GM 卡 · {self.user.nickname}"
