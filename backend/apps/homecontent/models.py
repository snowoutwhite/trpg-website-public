"""站长内容（homecontent）：首页可配置内容 + 站长公告。"""

from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models.functions import Lower

from apps.gallery.models import PHOTO_MAX_BYTES
from common.models import TimeStampedModel

# --------------------------------------------------------------------------
# 上传限额与尺寸
# --------------------------------------------------------------------------

# 「大小上限与相册一致」（实施方案）：单张 10 MB，直接引用相册那个常量，不抄数字。
SITE_IMAGE_MAX_BYTES = PHOTO_MAX_BYTES

# 扩展名白名单：jpg / png / webp / avif（实施方案指定）。真正说了算的是魔数。
ALLOWED_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "avif")

# 三档尺寸。full 给首屏满幅底图，card 给团卡/战报卡派生的前景图，thumb 给列表与后台预览。
FULL_MAX_SIDE = 2560
CARD_MAX_SIDE = 1200
THUMB_MAX_SIDE = 400

# 快速选择那张插画只有一档（版面里最大就是 card 尺寸）。
QUICK_IMAGE_MAX_SIDE = CARD_MAX_SIDE

# 只收 http/https：`URLField` 默认还放行 ftp/ftps，官方链接是要渲染成 <a href> 的。
https_url_validator = URLValidator(schemes=["http", "https"])


# --------------------------------------------------------------------------
# 输入校验（挂在**模型字段**上，不是只挂在 serializer 上）
# --------------------------------------------------------------------------
#
# 为什么在这一层：站长内容是「A 方案」——站主在 Django 后台也能改（见 admin.py 文头），
# 后台是与 API 同级的第二条写入路径，同一条约束必须两条路都守得住。
# `official_url` 从一开始就是这么做的（模型字段挂 validator + 后台表单再挂一次），
# 这里把 `route` 与规则名的保留形式对齐到同一处。

#: 站内路由：单个 `/` 开头（`//` 是协议相对 URL，会跳出站），其余字符限制成
#: 路径/查询串里合法的那一小撮 —— `\`、空白与控制字符都不在白名单里。
ROUTE_RE = re.compile(r"^/(?!/)[A-Za-z0-9\-._~!$&'()*+,;=:@%/?#\[\]]*$")

ROUTE_ERROR = "只能填站内路由：以单个 / 开头，例如 /recruit；不接受站外地址"


def validate_internal_route(value: str) -> None:
    """`QuickEntry.route` 只能是站内路径。

    拒绝：`https://…`、`//host`（协议相对 URL）、`javascript:` / `data:` 之类的伪协议、
    反斜杠（IE/部分解析器把 `/\host` 当成 `//host`）、空白与控制字符、不以 `/` 开头的裸串。
    """
    if not ROUTE_RE.match((value or "").strip()):
        raise ValidationError(ROUTE_ERROR, code="invalid_route")


#: 前后各两个下划线的名字是保留形式：`__other__` 是「其他」筛选的哨兵
#: （`apps/siteconfig/services.py`）。站主真建出这么一条预设，前端筛选条会画出一个
#: 点下去返回**别人**结果的筹码 —— 一个自己永远选不中的分类。
RESERVED_NAME_ERROR = "前后各两个下划线是保留形式（如「其他」筛选的哨兵 __other__），换一个规则名"


def validate_preset_name(value: str) -> None:
    """规则名不得撞上保留形式（大小写不敏感）。"""
    name = (value or "").strip().lower()
    if len(name) >= 4 and name.startswith("__") and name.endswith("__"):
        raise ValidationError(RESERVED_NAME_ERROR, code="reserved_name")


#: 规则名撞车（不分大小写）时的统一话术，serializer / 后台表单 / 模型 clean 共用一句。
NAME_TAKEN_ERROR = "已经有同名（不分大小写）的规则预设了"


def site_image_upload_to(instance, filename: str) -> str:
    """公开 media 目录 + uuid 文件名；用户的原始文件名一个字符都不进路径。

    只认服务端自己传进来的档位名（full / card / thumb / quick），认不出就叫 img；
    后缀恒为 .webp（所有档都重编码过）。
    """
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    tier = stem if stem in ("full", "card", "thumb", "quick") else "img"
    return f"homecontent/{uuid.uuid4().hex}-{tier}.webp"


# --------------------------------------------------------------------------
# 规则系统预设
# --------------------------------------------------------------------------

TONE_LIGHT = "light"
TONE_DARK = "dark"
TONE_CHOICES = [(TONE_LIGHT, "浅色画面（配深色字）"), (TONE_DARK, "深色画面（配浅色字）")]


class RuleSystemPreset(TimeStampedModel):
    """一个站级规则系统预设 = 首屏轮播的一帧 + 全站分类轴的一个取值。

    `name` 与 `SiteConfig.rule_system_presets` 对齐：**本表是唯一真源**，
    那个 JSON 字段退化成由本表同步出来的只读镜像（见 `services.sync_rule_system_presets`）。
    """

    name = models.CharField(
        "规则名", max_length=60, unique=True,
        validators=[validate_preset_name],
        help_text=(
            "全站分类轴的取值，团与角色卡的 rule_system 字段按它对齐（大小写不敏感地唯一）；"
            "前后各两个下划线的名字（如 __other__）是保留形式"
        ),
    )
    kicker = models.CharField(
        "英文眼标", max_length=60, blank=True, default="", help_text="如 DUNGEONS & DRAGONS"
    )
    title = models.CharField("中文标题", max_length=60, blank=True, default="", help_text="如 龙与地下城")
    tagline = models.CharField(
        "一句话标签", max_length=120, blank=True, default="", help_text="如 奇幻冒险 · 探索 · 社交 · 战斗"
    )

    # 「介绍三段」：首屏那句文案 + 规则介绍 + 适合谁。分成三个字段而不是一个 JSON，
    # 是为了让后台能逐段编辑、也让序列化器逐段做长度校验。
    intro_hero = models.TextField(
        "第一段·首屏一句话", blank=True, default="", help_text="如 掷下骰子，让想象中的世界成为你的冒险。"
    )
    intro_body = models.TextField("第二段·规则介绍", blank=True, default="")
    intro_fit = models.TextField("第三段·适合谁", blank=True, default="")

    official_url = models.URLField(
        "官方链接", max_length=300, blank=True, default="",
        validators=[https_url_validator],
        help_text="只收 http/https",
    )

    image_full = models.ImageField(
        "配图·满幅", upload_to=site_image_upload_to, max_length=255, blank=True, null=True
    )
    image_card = models.ImageField(
        "配图·卡片", upload_to=site_image_upload_to, max_length=255, blank=True, null=True
    )
    image_thumb = models.ImageField(
        "配图·缩略", upload_to=site_image_upload_to, max_length=255, blank=True, null=True
    )
    image_alt = models.CharField(
        "配图替代文字", max_length=200, blank=True, default="",
        help_text="读屏用户听到的描述；上传图片就该写",
    )
    tone = models.CharField(
        "画面明暗", max_length=8, choices=TONE_CHOICES, default=TONE_DARK,
        help_text="决定首屏那一帧的文字用深色还是浅色",
    )

    sort = models.PositiveIntegerField("排序", default=0, help_text="小的在前")

    class Meta:
        verbose_name = "规则系统预设"
        verbose_name_plural = "规则系统预设"
        ordering = ["sort", "id"]
        constraints = [
            # 唯一性的**真源在 DB**：`unique=True` 是大小写敏感的（PostgreSQL 与 SQLite
            # 的默认排序规则都如此），挡不住 `DND` / `dnd`。只靠 serializer 里的
            # `__iexact` 查询是「先查再写」—— 绕过 serializer 的写入点（后台、shell、
            # 数据迁移）一路畅通，两个站主同时点保存也会各自查到「没有重名」双双写进去。
            models.UniqueConstraint(Lower("name"), name="homecontent_preset_name_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def name_conflict(cls, name: str, *, exclude_pk=None):
        """返回与 `name` 大小写不敏感撞车的那一条（没有就是 None）。

        serializer / 后台表单 / `clean()` 共用这一处，免得三处各写一遍 `__iexact`。
        DB 约束才是最后一道，这里只是为了给人话而不是一个 IntegrityError。
        """
        queryset = cls.objects.filter(name__iexact=(name or "").strip())
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset.first()

    def clean(self) -> None:
        """`full_clean()` 是后台 ModelForm 的必经之路，也是所有非 API 写入点的最后一道。"""
        super().clean()
        self.name = (self.name or "").strip()
        if not self.name:
            return
        validate_preset_name(self.name)
        if self.name_conflict(self.name, exclude_pk=self.pk) is not None:
            raise ValidationError({"name": NAME_TAKEN_ERROR})

    def image_tiers(self) -> dict[str, str]:
        """三档的公开 URL；没传图的档位给空串（前端自己决定怎么降级）。"""
        return {
            "full": self.image_full.url if self.image_full else "",
            "card": self.image_card.url if self.image_card else "",
            "thumb": self.image_thumb.url if self.image_thumb else "",
        }

    def stored_images(self) -> list:
        return [f for f in (self.image_full, self.image_card, self.image_thumb) if f]


# --------------------------------------------------------------------------
# 快速选择
# --------------------------------------------------------------------------

QUICK_ICONS = ("sprout", "compass", "flag", "folder", "book", "contact")
QUICK_ICON_CHOICES = [
    ("sprout", "新芽（新人）"),
    ("compass", "指南针（找团）"),
    ("flag", "旗帜（开团）"),
    ("folder", "文件夹（资源）"),
    ("book", "书（战报）"),
    ("contact", "名片（角色卡）"),
]


class QuickEntry(TimeStampedModel):
    """首页第二段「你想从哪里开始？」的一项。

    `route` 是**站内**路由（必须以单个 `/` 开头）：站主能改文案与去向，
    但改不出一个跳到站外的按钮 —— 校验挂在模型字段上（`validate_internal_route`），
    所以 API、Django 后台、shell 三条写入路径守的是同一条。
    """

    key = models.SlugField(
        "标识", max_length=32, unique=True,
        help_text="稳定标识，预置六项用 newbie/recruit/host/resources/reports/cards",
    )
    label = models.CharField("按钮标签", max_length=30, help_text="如 我是新人")
    description = models.CharField("按钮说明", max_length=60, blank=True, default="", help_text="如 先弄懂跑团怎么进行")
    icon = models.CharField("图标", max_length=20, choices=QUICK_ICON_CHOICES, default="compass")

    kicker = models.CharField("英文眼标", max_length=60, blank=True, default="")
    title = models.CharField(
        "标题", max_length=60, blank=True, default="",
        help_text="纯文本；要换行就直接敲回车，前端按 white-space 渲染，不接受 HTML 标签",
    )
    body = models.TextField("说明正文", blank=True, default="")
    button_text = models.CharField("按钮文案", max_length=30, blank=True, default="", help_text="如 阅读新人指南")
    route = models.CharField(
        "目标路由", max_length=120, default="/",
        validators=[validate_internal_route],
        help_text="站内路由，必须以单个 / 开头，如 /recruit；不接受站外地址",
    )

    image = models.ImageField(
        "配图", upload_to=site_image_upload_to, max_length=255, blank=True, null=True
    )
    image_alt = models.CharField("配图替代文字", max_length=200, blank=True, default="")

    sort = models.PositiveIntegerField("排序", default=0, help_text="小的在前")

    class Meta:
        verbose_name = "快速选择入口"
        verbose_name_plural = "快速选择入口"
        ordering = ["sort", "id"]

    def __str__(self) -> str:
        return self.label


# --------------------------------------------------------------------------
# 站长公告
# --------------------------------------------------------------------------


class SiteAnnouncement(TimeStampedModel):
    """一条站长公告。生效时给全站活跃用户各推一条 `site_announcement` 通知。

    `notified_at` 是**推送幂等的锚**：推过就再不推第二遍（反复保存、反复切
    is_active、后台批量动作都不会重复轰炸全站）。想重新通知一次只能新建一条公告。
    """

    title = models.CharField("标题", max_length=100)
    body = models.TextField("正文", help_text="纯文本；前端不做 HTML 渲染")
    published_at = models.DateTimeField(
        "发布时间", db_index=True,
        help_text=(
            "未来时间 = 预告：到点之前不进公开列表也不推送；到点后由"
            " `manage.py announcements_publish_due`（生产 cron 每小时）补推一轮，"
            "公开列表被访问时也会顺手补推。留空 = 此刻"
        ),
    )
    is_active = models.BooleanField("生效中", default=True, db_index=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_announcements",
        verbose_name="作者",
    )
    notified_at = models.DateTimeField("已推送时间", null=True, blank=True, editable=False)
    notified_count = models.PositiveIntegerField("推送人数", default=0, editable=False)

    class Meta:
        verbose_name = "站长公告"
        verbose_name_plural = "站长公告"
        ordering = ["-published_at", "-id"]
        indexes = [models.Index(fields=["is_active", "-published_at"])]

    def __str__(self) -> str:
        return self.title
