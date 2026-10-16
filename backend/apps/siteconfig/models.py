"""站级单例配置。"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from common.models import TimeStampedModel

# 相册审核模式（需求 5：站级三选项）
GALLERY_MODE_PUBLIC = "public"
GALLERY_MODE_PRE_REVIEW = "pre_review"
GALLERY_MODE_POST_REPORT = "post_report"
GALLERY_MODE_CHOICES = [
    (GALLERY_MODE_PUBLIC, "默认公开"),
    (GALLERY_MODE_PRE_REVIEW, "公开前审核"),
    (GALLERY_MODE_POST_REPORT, "举报后下架"),
]

DEFAULT_RULE_SYSTEM_PRESETS = ["FU", "COC", "DND", "三角机构"]


def default_rule_system_presets() -> list[str]:
    return list(DEFAULT_RULE_SYSTEM_PRESETS)


# 精选照片的可见范围（v2 首页第四段旁的活动照片墙）
FEATURED_PHOTOS_PUBLIC = "public"
FEATURED_PHOTOS_MEMBERS = "members"
FEATURED_PHOTOS_VISIBILITY_CHOICES = [
    (FEATURED_PHOTOS_PUBLIC, "所有人可见（含游客）"),
    (FEATURED_PHOTOS_MEMBERS, "仅登录成员可见"),
]


class SiteConfig(TimeStampedModel):
    """全站唯一一行配置（pk 固定为 1）。"""

    SINGLETON_PK = 1

    # --- 功能开关 ---
    like_feature_enabled = models.BooleanField(
        "开启赞功能", default=True, help_text="关闭后评价入口隐藏、报名门槛失效，既有数据保留不删"
    )
    invite_code_required = models.BooleanField(
        "注册需要邀请码", default=False, help_text="开启后注册必须填写有效邀请码"
    )
    gallery_moderation_mode = models.CharField(
        "相册审核模式",
        max_length=20,
        choices=GALLERY_MODE_CHOICES,
        default=GALLERY_MODE_PUBLIC,
    )

    # --- 天数与窗口 ---
    auto_close_reminder_days = models.PositiveIntegerField(
        "自动结团提醒天数", default=3, validators=[MinValueValidator(1)],
        help_text="开团时间过去这么多天后提醒 GM 结团",
    )
    auto_close_days = models.PositiveIntegerField(
        "自动结团天数", default=7, validators=[MinValueValidator(1)],
        help_text="开团时间过去这么多天后系统自动结团",
    )
    gallery_upload_window_days = models.PositiveIntegerField(
        "相册上传窗口（天）", default=30, validators=[MinValueValidator(1)],
        help_text="结团后多少天内允许上传活动照片",
    )
    review_window_days = models.PositiveIntegerField(
        "评价窗口（天）", default=30, validators=[MinValueValidator(1)],
        help_text="结团后多少天内允许提交团后评价",
    )

    # --- 阈值 ---
    gm_auto_promote_threshold = models.PositiveIntegerField(
        "GM 自动晋升阈值", default=3, validators=[MinValueValidator(1)],
        help_text="作为 PL 被成功结团这么多次后自动获得 GM 身份",
    )
    like_level_publish_threshold = models.PositiveIntegerField(
        "赞级别公布阈值", default=10, validators=[MinValueValidator(1)],
        help_text="收到的评价数达到此值后才对外显示档位",
    )
    anon_throttle_per_minute = models.PositiveIntegerField(
        "游客限速（每分钟每 IP 请求数）", default=60, validators=[MinValueValidator(1)],
        help_text="未登录请求按公网 IP 计数；同一 WiFi 下多人共用一个 IP 时若频繁 429，把这个数调大即可，"
        "保存后立即生效，不用重启",
    )

    # --- 五档边界 ---

    # 分母 = 赞 + 倒赞 + 无评价。判定顺序：赞占比 ≥ 好评如潮 → 赞占比 ≥ 好评居多
    # → 倒赞占比 ≥ 差评如潮 → 倒赞占比 ≥ 倒赞居多 → 其余中性。
    level_overwhelmingly_positive_min = models.DecimalField(
        "好评如潮下限（赞占比）", max_digits=4, decimal_places=3, default=Decimal("0.800")
    )
    level_mostly_positive_min = models.DecimalField(
        "好评居多下限（赞占比）", max_digits=4, decimal_places=3, default=Decimal("0.600")
    )
    level_overwhelmingly_negative_dislike_min = models.DecimalField(
        "差评如潮下限（倒赞占比）", max_digits=4, decimal_places=3, default=Decimal("0.600")
    )
    level_mostly_negative_dislike_min = models.DecimalField(
        "倒赞居多下限（倒赞占比）", max_digits=4, decimal_places=3, default=Decimal("0.400"),
        help_text="赞占比与倒赞占比恰好同时达标时（如赞 60%、倒赞 40%）先按好评判",
    )

    # --- 预设与文案 ---
    rule_system_presets = models.JSONField(
        "规则系统预设（只读镜像）", default=default_rule_system_presets,
        help_text=(
            "字符串数组；玩家偏好规则与团的规则字段共用这一份列表。"
            "**唯一真源是「规则系统预设」表（homecontent.RuleSystemPreset）**，"
            "本字段由它自动同步出来，直接改这里会在下次同步时被覆盖。"
        ),
    )
    site_name = models.CharField("站名", max_length=60, default="跑团网站")
    announcement = models.TextField("公告栏文案", blank=True, default="")
    footer_tagline = models.CharField(
        "页脚署名句", max_length=60, blank=True, default="让冒险者相遇",
        help_text="页脚站名后面那半句；留空则只显示站名",
    )

    # --- 首页第三、四段的标题组（内容取自 v2 index.html，站主可改）---
    home_section3_kicker = models.CharField(
        "首页第三段·英文眼标", max_length=60, blank=True, default="OPEN TABLES"
    )
    home_section3_title = models.CharField(
        "首页第三段·标题", max_length=60, blank=True, default="正在招募的团"
    )
    home_section3_lead = models.TextField(
        "首页第三段·导语", blank=True,
        default="看到合适的座位就进去看看公告。报名者身份只对登录成员可见，正式名单只对同团成员可见。",
    )
    home_section4_kicker = models.CharField(
        "首页第四段·英文眼标", max_length=60, blank=True, default="STORIES WORTH KEEPING"
    )
    home_section4_title = models.CharField(
        "首页第四段·标题", max_length=60, blank=True, default="留下的故事"
    )
    home_section4_lead = models.TextField(
        "首页第四段·导语", blank=True,
        default="站主从成员的战报里挑出来的几篇。骰子停下之后，故事由写下它的人继续。",
    )

    # --- 精选活动照片（首页照片墙）---
    featured_photos_enabled = models.BooleanField(
        "首页展示精选活动照片", default=False,
        help_text="默认关。开启前请确认被拍到者的下架诉求入口仍然通畅",
    )
    featured_photos_visibility = models.CharField(
        "精选照片可见范围",
        max_length=10,
        choices=FEATURED_PHOTOS_VISIBILITY_CHOICES,
        default=FEATURED_PHOTOS_MEMBERS,
        help_text="相册整体是「需登录」的，选 public 等于对这一小撮照片单独开口子",
    )
    icp_beian = models.CharField(
        "ICP 备案号",
        max_length=64,
        blank=True,
        default="",
        help_text="页脚展示的工信部备案号，如「京ICP备00000000号-1」；没有就留空，前端不渲染页脚备案行",
    )

    class Meta:
        verbose_name = "站点配置"
        verbose_name_plural = "站点配置"

    def __str__(self) -> str:
        return self.site_name

    def clean(self) -> None:
        super().clean()
        like_bounds = (self.level_overwhelmingly_positive_min, self.level_mostly_positive_min)
        dislike_bounds = (
            self.level_overwhelmingly_negative_dislike_min,
            self.level_mostly_negative_dislike_min,
        )
        bounds = (*like_bounds, *dislike_bounds)
        if all(b is not None for b in bounds):
            if not all(0 < b <= 1 for b in bounds):
                raise ValidationError("五档边界必须大于 0、不超过 1")
            if not like_bounds[0] > like_bounds[1]:
                raise ValidationError("「好评如潮」的赞占比下限必须高于「好评居多」")
            if not dislike_bounds[0] > dislike_bounds[1]:
                raise ValidationError("「差评如潮」的倒赞占比下限必须高于「倒赞居多」")
        if self.auto_close_days < self.auto_close_reminder_days:
            raise ValidationError("自动结团天数不能小于自动结团提醒天数")

    def save(self, *args, **kwargs):
        # 单例：永远写在 pk=1 上。
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)
        from apps.siteconfig.services import clear_config_cache

        clear_config_cache()

    def delete(self, *args, **kwargs):  # pragma: no cover - 单例不允许删
        raise RuntimeError("站点配置是单例，不允许删除")
