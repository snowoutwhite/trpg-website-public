"""团（games）：标签、团公告、报名、场次。"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.profiles.levels import LEVEL_CHOICES
from common.models import TimeStampedModel

# --------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------

# 开团方式：线上 / 线下二选一
MODE_ONLINE = "online"
MODE_OFFLINE = "offline"
MODE_CHOICES = [
    (MODE_ONLINE, "线上"),
    (MODE_OFFLINE, "线下"),
]

# 报名模式
SIGNUP_FIRST_COME = "first_come"
SIGNUP_POOL_REVIEW = "pool_review"
SIGNUP_MODE_CHOICES = [
    (SIGNUP_FIRST_COME, "先到先得"),
    (SIGNUP_POOL_REVIEW, "PL 池 + 人工审核"),
]

# 团状态机
GAME_RECRUITING = "recruiting"
GAME_CLOSED_SIGNUP = "closed_signup"
GAME_RUNNING = "running"
GAME_FINISHED = "finished"
GAME_CANCELLED = "cancelled"
GAME_STATUS_CHOICES = [
    (GAME_RECRUITING, "招募中"),
    (GAME_CLOSED_SIGNUP, "报名已满"),
    (GAME_RUNNING, "进行中"),
    (GAME_FINISHED, "已结团"),
    (GAME_CANCELLED, "已取消"),
]
# 还能报名 / 还能交卡的两个状态
OPEN_STATUSES = (GAME_RECRUITING, GAME_CLOSED_SIGNUP)

# 报名状态机
SIGNUP_PENDING = "pending"
SIGNUP_SUBMITTED = "submitted"
SIGNUP_ACCEPTED = "accepted"
SIGNUP_REJECTED = "rejected"
SIGNUP_WITHDRAWN = "withdrawn"
SIGNUP_REMOVED = "removed"
SIGNUP_NO_CARD = "no_card"
SIGNUP_STATUS_CHOICES = [
    (SIGNUP_PENDING, "待交卡"),
    (SIGNUP_SUBMITTED, "已交卡待审"),
    (SIGNUP_ACCEPTED, "成功报团"),
    (SIGNUP_REJECTED, "未通过"),
    (SIGNUP_WITHDRAWN, "已退出"),
    (SIGNUP_REMOVED, "被移出"),
    (SIGNUP_NO_CARD, "未交卡"),
]
# 占位的三种状态：这三种都算占着团里的一个位置（满员判断用）
OCCUPYING_STATUSES = (SIGNUP_PENDING, SIGNUP_SUBMITTED, SIGNUP_ACCEPTED)
# 还活着的报名（可被 GM 处置的）
ACTIVE_STATUSES = (SIGNUP_PENDING, SIGNUP_SUBMITTED, SIGNUP_ACCEPTED, SIGNUP_NO_CARD)

# 预设标签（数据迁移里创建，站主在后台维护）
PRESET_TAGS = ["战役", "西征"]


class Tag(TimeStampedModel):
    """团的关键词 = 标签。"""

    name = models.CharField("标签", max_length=30, unique=True)
    is_preset = models.BooleanField(
        "预设标签", default=False, help_text="预设标签由站主维护，不随 GM 输入新建"
    )

    class Meta:
        verbose_name = "团标签"
        verbose_name_plural = "团标签"
        ordering = ["-is_preset", "name"]

    def __str__(self) -> str:
        return self.name


class Game(TimeStampedModel):
    """业务规则与安全约束。"""

    gm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hosted_games",
        verbose_name="GM",
    )
    title = models.CharField("标题", max_length=80)
    announcement = models.TextField("公告正文", blank=True, default="")
    rule_system = models.CharField(
        "规则系统",
        max_length=60,
        blank=True,
        default="",
        help_text="可选站点预设（siteconfig.rule_system_presets），也可自定义文本",
    )
    start_at = models.DateTimeField("预计开团时间", db_index=True, help_text="精确到分钟")
    mode = models.CharField("开团方式", max_length=16, choices=MODE_CHOICES, default=MODE_ONLINE)
    location = models.CharField(
        "开团地点", max_length=120, blank=True, default="", help_text="线上填平台/频道，线下填地址"
    )
    requirements = models.TextField(
        "开团需求", blank=True, default="", help_text="首发为长文本，由 GM 自由填写"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="games", verbose_name="标签")

    min_players = models.PositiveIntegerField("最少人数", default=1)
    max_players = models.PositiveIntegerField("最多人数", default=5)

    signup_mode = models.CharField(
        "报名模式", max_length=16, choices=SIGNUP_MODE_CHOICES, default=SIGNUP_FIRST_COME
    )

    # --- 报名门槛：两个独立可选字段，留空 = 不设 ---
    min_play_count = models.PositiveIntegerField(
        "最低团次数", null=True, blank=True, help_text="留空表示不设；看玩家卡的参团次数"
    )
    min_level = models.CharField(
        "最低赞级别",
        max_length=32,
        choices=LEVEL_CHOICES,
        blank=True,
        default="",
        help_text="留空表示不设；无档位者（评价数不足公布阈值）不能报设了此门槛的团",
    )

    requires_card = models.BooleanField(
        "需要交卡", default=True, help_text="取消勾选 = 免交卡团，报名通过即成功报团"
    )
    card_deadline = models.DateTimeField(
        "交卡截止", help_text="默认 = 预计开团时间；GM 可改，但不得晚于开团时间"
    )

    mutual_review = models.BooleanField(
        "评价互见", default=False, help_text="开启后同团成员可看到彼此收到的匿名评价"
    )

    # --- 战役后续团 ---
    campaign_prev = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_games",
        verbose_name="前一个团",
        help_text="战役的后续团指向前团；人数范围默认沿用前团",
    )
    restrict_to_prev_members = models.BooleanField(
        "仅限前团成员", default=False, help_text="只有前团实际到场者能报名"
    )

    status = models.CharField(
        "状态", max_length=16, choices=GAME_STATUS_CHOICES, default=GAME_RECRUITING, db_index=True
    )
    cancel_reason = models.TextField("取消理由", blank=True, default="")
    finished_at = models.DateTimeField("结团时间", null=True, blank=True, db_index=True)

    # --- 定时提醒去重标记（management command 用，不对外暴露）---
    card_deadline_reminded_at = models.DateTimeField("交卡提醒发出时间", null=True, blank=True)
    start_reminded_at = models.DateTimeField("开团提醒发出时间", null=True, blank=True)
    close_reminded_at = models.DateTimeField("结团提醒发出时间", null=True, blank=True)
    auto_closed = models.BooleanField("由系统自动结团", default=False)

    class Meta:
        verbose_name = "团"
        verbose_name_plural = "团"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-start_at"]),
            models.Index(fields=["gm", "status"]),
        ]

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        super().clean()
        if self.min_players and self.max_players and self.min_players > self.max_players:
            raise ValidationError("最少人数不能大于最多人数")
        if self.start_at and self.card_deadline and self.card_deadline > self.start_at:
            raise ValidationError("交卡截止不得晚于开团时间。")

    # --- 只读派生属性（序列化器与 services 共用）---

    @property
    def is_open_for_signup(self) -> bool:
        return self.status == GAME_RECRUITING

    @property
    def occupied_seats(self) -> int:
        """占位人数 = 待交卡 + 已交卡待审 + 成功报团（满员判断口径）。"""
        return self.signups.filter(status__in=OCCUPYING_STATUSES).count()

    @property
    def accepted_count(self) -> int:
        return self.signups.filter(status=SIGNUP_ACCEPTED).count()

    @property
    def is_full(self) -> bool:
        return self.occupied_seats >= self.max_players

    @property
    def is_over(self) -> bool:
        return self.status in (GAME_FINISHED, GAME_CANCELLED)


class Signup(TimeStampedModel):
    """一份报名。"""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="signups", verbose_name="团")
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="game_signups",
        verbose_name="报名者",
    )
    order = models.PositiveIntegerField("报名顺序", default=1)
    status = models.CharField(
        "状态", max_length=16, choices=SIGNUP_STATUS_CHOICES, default=SIGNUP_PENDING, db_index=True
    )

    card = models.ForeignKey(
        "charactercards.CharacterCard",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="game_signups",
        verbose_name="交上来的角色卡",
    )
    card_uploaded_by_gm = models.BooleanField(
        "GM 代传卡", default=False, help_text="卡归 PL，注明「GM 上传」"
    )
    card_submitted_at = models.DateTimeField("交卡时间", null=True, blank=True)

    review_note = models.TextField("审批/处置备注", blank=True, default="")
    decided_at = models.DateTimeField("审批时间", null=True, blank=True)

    withdraw_requested_at = models.DateTimeField(
        "申请退出时间", null=True, blank=True, help_text="截止后退出需 GM 确认，先落一条申请"
    )
    withdraw_reason = models.TextField("退出理由", blank=True, default="")

    attended = models.BooleanField(
        "实际到场", default=False, help_text="结团时由 GM 勾选；只有到场者计次数与配额"
    )

    class Meta:
        verbose_name = "报名"
        verbose_name_plural = "报名"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["game", "player"], name="uniq_signup_per_game_player")
        ]
        indexes = [
            models.Index(fields=["game", "status"]),
            models.Index(fields=["player", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.player.nickname} @ {self.game.title}"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


class Session(TimeStampedModel):
    """团内场次（第 0 回、第 1 回…）。首发只做 CRUD，不参与任何计数。"""

    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name="sessions", verbose_name="团"
    )
    index = models.PositiveIntegerField("场次序号", default=0, help_text="0 表示「第 0 回」")
    label = models.CharField("场次名称", max_length=60, blank=True, default="")
    held_at = models.DateTimeField("举行时间", null=True, blank=True)

    class Meta:
        verbose_name = "场次"
        verbose_name_plural = "场次"
        ordering = ["index", "id"]
        constraints = [
            models.UniqueConstraint(fields=["game", "index"], name="uniq_session_index_per_game")
        ]

    def __str__(self) -> str:
        return self.label or f"第 {self.index} 回"

    @property
    def display_label(self) -> str:
        return self.label or f"第 {self.index} 回"
