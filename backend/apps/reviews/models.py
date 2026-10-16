"""团后评价（reviews）：三档匿名评价的存储层。"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel

# --------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------

# 三档里只有两档会落库；「无评价」= 没有行
VERDICT_LIKE = "like"
VERDICT_DISLIKE = "dislike"
VERDICT_CHOICES = [
    (VERDICT_LIKE, "赞"),
    (VERDICT_DISLIKE, "倒赞"),
]

# 被评者在该团里的身份：决定这条评价算进 GM 卡还是玩家卡
ROLE_GM = "gm"
ROLE_PL = "pl"
ROLE_CHOICES = [
    (ROLE_GM, "GM"),
    (ROLE_PL, "PL"),
]


class Review(TimeStampedModel):
    """一条团后评价：某人在某团里给某人的赞或倒赞，必附文字。"""

    game = models.ForeignKey(
        "games.Game", on_delete=models.CASCADE, related_name="reviews", verbose_name="团"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews_given",
        verbose_name="评价人",
        help_text="匿名红线：除了本人回顾，任何接口都不得回传此字段",
    )
    reviewee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews_received",
        verbose_name="被评者",
    )
    verdict = models.CharField("评级", max_length=16, choices=VERDICT_CHOICES)
    text = models.TextField("评价内容", help_text="赞与倒赞都必须附文字")
    reviewee_role = models.CharField(
        "被评者身份",
        max_length=8,
        choices=ROLE_CHOICES,
        help_text="被评者在该团里的身份；GM 评价进 GM 卡，PL 评价进玩家卡",
    )

    class Meta:
        verbose_name = "团后评价"
        verbose_name_plural = "团后评价"
        # **故意不设 ordering**：默认按 id / created_at 排序会把提交顺序泄露给被评者。
        # 面向被评者的顺序一律走 services.anonymize_order()。
        constraints = [
            models.UniqueConstraint(
                fields=["game", "reviewer", "reviewee"], name="uniq_review_per_game_pair"
            ),
            models.CheckConstraint(
                condition=~models.Q(reviewer=models.F("reviewee")), name="review_not_self"
            ),
        ]
        indexes = [
            models.Index(fields=["reviewee", "reviewee_role"]),
            models.Index(fields=["game", "reviewee"]),
            models.Index(fields=["reviewer"]),
        ]

    def __str__(self) -> str:
        # 注意：__str__ 会进后台日志与删除确认页，**不能带评价人**。
        return f"{self.game_id} 号团收到的一条评价"


class ReviewWindowNotice(TimeStampedModel):
    """「评价窗口即将关闭」提醒的发送去重标记（每团一次）。

    放在本 app 而不是给 `games.Game` 加字段：并行波次里不改别人的表。
    """

    game = models.OneToOneField(
        "games.Game",
        on_delete=models.CASCADE,
        related_name="review_window_notice",
        verbose_name="团",
    )
    sent_at = models.DateTimeField("提醒发出时间", auto_now_add=True)

    class Meta:
        verbose_name = "评价窗口提醒记录"
        verbose_name_plural = "评价窗口提醒记录"

    def __str__(self) -> str:
        return f"{self.game_id} 号团的窗口提醒"


class ReviewWindowClosure(TimeStampedModel):
    """「评价窗口已关闭、卡片已按含无评价的口径重算」的去重标记（每团一次）。

    「无评价」只在窗口关闭后计入被评次数（`services.review_counts`），窗口关闭又是
    纯时间事件，所以由每小时的 `reviews_window_closing` 命令发现并重算到场成员的卡。
    """

    game = models.OneToOneField(
        "games.Game",
        on_delete=models.CASCADE,
        related_name="review_window_closure",
        verbose_name="团",
    )

    class Meta:
        verbose_name = "评价窗口关闭重算记录"
        verbose_name_plural = "评价窗口关闭重算记录"

    def __str__(self) -> str:
        return f"{self.game_id} 号团的窗口关闭重算"
