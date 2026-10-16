"""站长内容后台（A 方案：站主在 Django 后台也能改，不必依赖前端编辑模式）。

两条纪律：
1. **图片不在后台直传**。后台的图片字段是只读的缩略预览，换图走
   `POST /api/v1/home/admin/<资源>/<id>/image/` —— 那条路径上才有
   「扩展名 + 魔数 + 像素上限 + EXIF 剥离 + 三档编码」那一整套。
   让后台的 `ImageField` 直接收文件等于给站主开一条把任意字节写进公开
   media 目录的口子（原始 EXIF/GPS 也会原样留在服务器上）。
2. **公告推送走 service**。保存公告时调 `services.publish_announcement`，
   它自己保证一条公告只推一轮；不要在后台直接改 `notified_at`。
"""

from __future__ import annotations

from django import forms
from django.contrib import admin
from django.utils.html import format_html

from apps.homecontent import services
from apps.homecontent.models import (
    NAME_TAKEN_ERROR,
    QuickEntry,
    RuleSystemPreset,
    SiteAnnouncement,
    https_url_validator,
    validate_internal_route,
    validate_preset_name,
)


def _thumb(field, *, height: int = 60):
    """后台缩略预览。字段为空就给一个短横，不要渲染一个坏掉的 <img>。"""
    if not field:
        return "—"
    return format_html('<img src="{}" style="height:{}px;border-radius:4px" alt="">', field.url, height)


class RuleSystemPresetAdminForm(forms.ModelForm):
    """显式给官方链接定 scheme，并把规则名的两条约束在表单层也说一遍。

    官方链接两件事：① 只收 http/https（与 API 那边同一个 validator）；
    ② `assume_scheme="https"` —— 站主只敲 `need.games` 时补哪个协议，
    Django 6.0 会把默认从 http 改成 https，不写死就会在某次升级后静默变行为。

    规则名两件事：① 不分大小写地唯一；② `__other__` 这种保留形式不能用。
    模型上都有兜底（`UniqueConstraint(Lower("name"))` + `clean()`），这里再拦一道
    是为了让站主在**表单字段旁边**看到人话，而不是一个 500 或一条非字段错误。
    """

    official_url = forms.URLField(
        required=False, assume_scheme="https", validators=[https_url_validator]
    )

    class Meta:
        model = RuleSystemPreset
        fields = "__all__"

    def clean_name(self) -> str:
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            return name
        validate_preset_name(name)
        if RuleSystemPreset.name_conflict(name, exclude_pk=self.instance.pk) is not None:
            raise forms.ValidationError(NAME_TAKEN_ERROR)
        return name


class QuickEntryAdminForm(forms.ModelForm):
    """站内路由在表单层再挂一次（与 `official_url` 同一个做法）。

    模型字段上已经有 `validate_internal_route`，后台保存时会走到；这里显式挂上
    是为了让这条约束在后台这条写入路径上**看得见**，将来谁改了 fieldsets
    也不至于以为路由是随便填的。
    """

    route = forms.CharField(max_length=120, validators=[validate_internal_route])

    class Meta:
        model = QuickEntry
        fields = "__all__"


@admin.register(RuleSystemPreset)
class RuleSystemPresetAdmin(admin.ModelAdmin):
    form = RuleSystemPresetAdminForm
    list_display = ["name", "title", "tone", "sort", "thumb_preview"]
    list_editable = ["sort"]
    search_fields = ["name", "title", "kicker"]
    readonly_fields = [
        "image_full",
        "image_card",
        "image_thumb",
        "full_preview",
        "card_preview",
        "thumb_preview",
        "created_at",
        "updated_at",
    ]
    fieldsets = (
        ("分类轴", {"fields": ("name", "sort")}),
        ("文案", {"fields": ("kicker", "title", "tagline", "intro_hero", "intro_body", "intro_fit", "official_url")}),
        (
            "配图（换图走 API：POST /api/v1/home/admin/rule-presets/<id>/image/）",
            {"fields": ("tone", "image_alt", "full_preview", "card_preview", "thumb_preview", "image_full", "image_card", "image_thumb")},
        ),
        ("时间", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="满幅预览")
    def full_preview(self, obj: RuleSystemPreset):
        return _thumb(obj.image_full, height=120)

    @admin.display(description="卡片预览")
    def card_preview(self, obj: RuleSystemPreset):
        return _thumb(obj.image_card, height=90)

    @admin.display(description="缩略预览")
    def thumb_preview(self, obj: RuleSystemPreset):
        return _thumb(obj.image_thumb)


@admin.register(QuickEntry)
class QuickEntryAdmin(admin.ModelAdmin):
    form = QuickEntryAdminForm
    list_display = ["label", "key", "icon", "route", "sort", "image_preview"]
    list_editable = ["sort"]
    search_fields = ["label", "key", "title"]
    readonly_fields = ["image", "image_preview", "created_at", "updated_at"]
    fieldsets = (
        ("按钮", {"fields": ("key", "label", "description", "icon", "sort")}),
        ("详情面板", {"fields": ("kicker", "title", "body", "button_text", "route")}),
        (
            "配图（换图走 API：POST /api/v1/home/admin/quick-entries/<id>/image/）",
            {"fields": ("image_alt", "image_preview", "image")},
        ),
        ("时间", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="配图预览")
    def image_preview(self, obj: QuickEntry):
        return _thumb(obj.image, height=90)


@admin.register(SiteAnnouncement)
class SiteAnnouncementAdmin(admin.ModelAdmin):
    list_display = ["title", "published_at", "is_active", "author", "notified_at", "notified_count"]
    list_filter = ["is_active"]
    search_fields = ["title", "body"]
    readonly_fields = ["notified_at", "notified_count", "created_at", "updated_at"]

    def save_model(self, request, obj, form, change) -> None:
        """保存后按需推送一轮（幂等，推过的公告不会再推）。"""
        if obj.author_id is None:
            obj.author = request.user
        super().save_model(request, obj, form, change)
        services.publish_announcement(obj)
