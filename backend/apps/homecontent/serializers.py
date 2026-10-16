"""站长内容序列化。"""

from __future__ import annotations

import re

from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.homecontent.models import (
    NAME_TAKEN_ERROR,
    QuickEntry,
    RuleSystemPreset,
    SiteAnnouncement,
    https_url_validator,
    validate_internal_route,
    validate_preset_name,
)
from apps.siteconfig.models import SiteConfig
from common.params import PK_MAX
from common.text import validate_no_bidi_controls

_TAG_RE = re.compile(r"<[^>]*>")


def reject_markup(value: str) -> str:
    if value and _TAG_RE.search(value):
        raise serializers.ValidationError("这里只收纯文本，不要写 HTML 标签；需要换行就直接敲回车")
    return value


class PlainTextField(serializers.CharField):
    """纯文本字段：拒绝 HTML 标签与文字方向控制字符，两端留白照常清掉。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.validators.append(validate_no_bidi_controls)

    def to_internal_value(self, data):
        return reject_markup(super().to_internal_value(data))


# --------------------------------------------------------------------------
# 公开读
# --------------------------------------------------------------------------


class RuleSystemPresetSerializer(serializers.ModelSerializer):
    """首屏轮播一帧 + 全站分类轴一个取值。"""

    image = serializers.SerializerMethodField()
    intro = serializers.SerializerMethodField()

    class Meta:
        model = RuleSystemPreset
        fields = [
            "id",
            "name",
            "kicker",
            "title",
            "tagline",
            "intro",
            "official_url",
            "image",
            "image_alt",
            "tone",
            "sort",
        ]
        read_only_fields = fields

    def get_image(self, obj: RuleSystemPreset) -> dict:
        return obj.image_tiers()

    def get_intro(self, obj: RuleSystemPreset) -> dict:
        return {"hero": obj.intro_hero, "body": obj.intro_body, "fit": obj.intro_fit}


class QuickEntrySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = QuickEntry
        fields = [
            "id",
            "key",
            "label",
            "description",
            "icon",
            "kicker",
            "title",
            "body",
            "button_text",
            "route",
            "image",
            "image_alt",
            "sort",
        ]
        read_only_fields = fields

    def get_image(self, obj: QuickEntry) -> str:
        return obj.image.url if obj.image else ""


class SiteAnnouncementSerializer(serializers.ModelSerializer):
    """公开的公告表示。`is_read` / `notification_id` 由上下文里的 `read_map` 填。"""

    author = PublicUserSerializer(read_only=True)
    is_read = serializers.SerializerMethodField()
    notification_id = serializers.SerializerMethodField()

    class Meta:
        model = SiteAnnouncement
        fields = [
            "id",
            "title",
            "body",
            "published_at",
            "author",
            "is_read",
            "notification_id",
        ]
        read_only_fields = fields

    def _notification(self, obj: SiteAnnouncement):
        return (self.context.get("read_map") or {}).get(obj.pk)

    def get_is_read(self, obj: SiteAnnouncement) -> bool | None:
        """游客没有已读状态，回 `null`；登录用户回真/假。

        「已读」的真源是那条站内通知（实施方案：已读 = 对应通知标已读），
        没收到通知的老用户（公告在他注册之前推的）同样回 `null`。
        """
        notification = self._notification(obj)
        if notification is None:
            return None
        return notification.read_at is not None

    def get_notification_id(self, obj: SiteAnnouncement) -> int | None:
        notification = self._notification(obj)
        return notification.pk if notification else None


class HomeSiteCopySerializer(serializers.ModelSerializer):
    """首页的站级文案块。运维参数一个都不带。"""

    section3 = serializers.SerializerMethodField()
    section4 = serializers.SerializerMethodField()

    class Meta:
        model = SiteConfig
        fields = ["site_name", "announcement", "footer_tagline", "section3", "section4"]
        read_only_fields = fields

    def get_section3(self, obj: SiteConfig) -> dict:
        return {
            "kicker": obj.home_section3_kicker,
            "title": obj.home_section3_title,
            "lead": obj.home_section3_lead,
        }

    def get_section4(self, obj: SiteConfig) -> dict:
        return {
            "kicker": obj.home_section4_kicker,
            "title": obj.home_section4_title,
            "lead": obj.home_section4_lead,
        }


class FeaturedPhotoSerializer(serializers.Serializer):
    """首页照片墙的一张照片。

    **故意不带 uploader**：首页不需要知道是谁传的，而这份响应在
    `featured_photos_visibility=public` 时连游客都看得到。
    图片字节走 `home/featured-photos/<id>/file/`，不回传任何存储路径。
    """

    id = serializers.IntegerField(read_only=True)
    caption = serializers.CharField(read_only=True)
    game_id = serializers.IntegerField(read_only=True)
    game_title = serializers.SerializerMethodField()
    width = serializers.IntegerField(read_only=True)
    height = serializers.IntegerField(read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()

    def get_game_title(self, obj) -> str:
        return obj.game.title

    def _url(self, obj, size: str) -> str:
        from django.urls import reverse

        return f"{reverse('v1:homecontent:featured-photo-file', kwargs={'pk': obj.pk})}?size={size}"

    def get_thumbnail_url(self, obj) -> str:
        return self._url(obj, "thumb")

    def get_preview_url(self, obj) -> str:
        return self._url(obj, "preview")


class AdminFeaturedCandidateSerializer(FeaturedPhotoSerializer):
    """站主挑精选的候选照片（`home/admin/featured-photos/candidates/`）。

    在首页那份字段之上多两项：`is_featured` 现状、`created_at`；图片字节改走相册的鉴权出口
    `gallery/photos/<pk>/file/`——首页那条出口只放行「已精选 + 已公开」，候选池里多数还没精选。
    仍然不带 uploader（站主要查是谁传的去相册 / 后台）。
    """

    is_featured = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def _url(self, obj, size: str) -> str:
        from django.urls import reverse

        return f"{reverse('v1:gallery:photo-file', kwargs={'pk': obj.pk})}?size={size}"


# --------------------------------------------------------------------------
# staff 写
# --------------------------------------------------------------------------


class RuleSystemPresetWriteSerializer(serializers.ModelSerializer):
    """站主改规则预设。图片不走这里（走 multipart 的专用接口）。"""

    # 显式上界：SQLite 不管 PositiveIntegerField 的 32 位上界，`2**31` 在本机会静默入库。
    sort = serializers.IntegerField(min_value=0, max_value=PK_MAX, required=False)

    name = PlainTextField(max_length=60)
    kicker = PlainTextField(max_length=60, required=False, allow_blank=True)
    title = PlainTextField(max_length=60, required=False, allow_blank=True)
    tagline = PlainTextField(max_length=120, required=False, allow_blank=True)
    intro_hero = PlainTextField(max_length=500, required=False, allow_blank=True)
    intro_body = PlainTextField(max_length=2000, required=False, allow_blank=True)
    intro_fit = PlainTextField(max_length=2000, required=False, allow_blank=True)
    image_alt = PlainTextField(max_length=200, required=False, allow_blank=True)
    official_url = serializers.URLField(
        max_length=300, required=False, allow_blank=True, validators=[https_url_validator]
    )

    class Meta:
        model = RuleSystemPreset
        fields = [
            "name",
            "kicker",
            "title",
            "tagline",
            "intro_hero",
            "intro_body",
            "intro_fit",
            "official_url",
            "image_alt",
            "tone",
            "sort",
        ]

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("规则名不能为空")
        # 保留形式（`__other__` 之流）：DRF 会把 Django 的 ValidationError 翻成字段级 400。
        validate_preset_name(value)
        # 规则名参与「其他」筛选（大小写不敏感），所以重名也得按不敏感判。
        # 真正的兜底是模型上的 `UniqueConstraint(Lower("name"))`，这里只为给人话。
        exclude_pk = self.instance.pk if self.instance is not None else None
        if RuleSystemPreset.name_conflict(value, exclude_pk=exclude_pk) is not None:
            raise serializers.ValidationError(NAME_TAKEN_ERROR)
        return value


class QuickEntryWriteSerializer(serializers.ModelSerializer):
    sort = serializers.IntegerField(min_value=0, max_value=PK_MAX, required=False)
    label = PlainTextField(max_length=30)
    description = PlainTextField(max_length=60, required=False, allow_blank=True)
    kicker = PlainTextField(max_length=60, required=False, allow_blank=True)
    title = PlainTextField(max_length=60, required=False, allow_blank=True)
    body = PlainTextField(max_length=2000, required=False, allow_blank=True)
    button_text = PlainTextField(max_length=30, required=False, allow_blank=True)
    image_alt = PlainTextField(max_length=200, required=False, allow_blank=True)

    class Meta:
        model = QuickEntry
        fields = [
            "key",
            "label",
            "description",
            "icon",
            "kicker",
            "title",
            "body",
            "button_text",
            "route",
            "image_alt",
            "sort",
        ]

    def validate_route(self, value: str) -> str:
        # `CharField` 默认会把两端留白（含换行）trim 掉，所以 "\n/recruit" 到这里
        # 已经是 "/recruit"；这里再 strip 一次只是不依赖那个默认值。
        value = (value or "").strip()
        validate_internal_route(value)  # 校验器本体在模型层，后台走的是同一个
        return value


class SiteAnnouncementWriteSerializer(serializers.ModelSerializer):
    title = PlainTextField(max_length=100)
    body = PlainTextField(max_length=10000)

    class Meta:
        model = SiteAnnouncement
        fields = ["title", "body", "published_at", "is_active"]
        extra_kwargs = {"published_at": {"required": False}}


class HomeConfigWriteSerializer(serializers.ModelSerializer):
    """站主改 SiteConfig 上属于「首页内容」的那几格。

    **只开这几格**：`SiteConfig` 上还有自动结团天数、五档边界这类运维参数，
    它们的编辑口是 Django 后台，不该顺着首页编辑模式的 PATCH 一起放出去。
    """

    footer_tagline = PlainTextField(max_length=60, required=False, allow_blank=True)
    announcement = PlainTextField(max_length=2000, required=False, allow_blank=True)
    home_section3_kicker = PlainTextField(max_length=60, required=False, allow_blank=True)
    home_section3_title = PlainTextField(max_length=60, required=False, allow_blank=True)
    home_section3_lead = PlainTextField(max_length=1000, required=False, allow_blank=True)
    home_section4_kicker = PlainTextField(max_length=60, required=False, allow_blank=True)
    home_section4_title = PlainTextField(max_length=60, required=False, allow_blank=True)
    home_section4_lead = PlainTextField(max_length=1000, required=False, allow_blank=True)
    site_name = PlainTextField(max_length=60, required=False)

    class Meta:
        model = SiteConfig
        fields = [
            "site_name",
            "announcement",
            "footer_tagline",
            "home_section3_kicker",
            "home_section3_title",
            "home_section3_lead",
            "home_section4_kicker",
            "home_section4_title",
            "home_section4_lead",
            "featured_photos_enabled",
            "featured_photos_visibility",
        ]


class ImageUploadSerializer(serializers.Serializer):
    """图片上传入参。

    故意用 `FileField` 而不是 `ImageField`：DRF 的 ImageField 会抢先用 Django 表单
    那套校验把非图片判成通用 validation_error，我们要的是 services 里那套
    「扩展名 + 魔数 + 像素上限」给出的 invalid_image / image_too_large 明确错误码
    （与相册 `PhotoUploadSerializer` 同一理由）。
    """

    file = serializers.FileField(write_only=True)


class FeaturePhotoSerializer(serializers.Serializer):
    """站主勾选/取消精选的入参。

    `max_value` 不是装饰：主键是 32 位整数，`{"photo": 10**20}` 不挡的话会一路送进
    `get_object_or_404`，在 PostgreSQL 上变成 `DataError` → 500（SQLite 上则静默查空，
    两个后端行为不一致本身就是坑）。与 `common.params.parse_pk` 同一条边界。
    """

    photo = serializers.IntegerField(min_value=1, max_value=PK_MAX)
    is_featured = serializers.BooleanField()
