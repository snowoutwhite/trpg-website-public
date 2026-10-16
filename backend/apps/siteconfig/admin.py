"""站点配置后台：单例编辑，不允许新增第二行、不允许删除。"""

from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse

from apps.siteconfig.models import SiteConfig


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    fieldsets = (
        ("功能开关", {"fields": ("like_feature_enabled", "invite_code_required", "gallery_moderation_mode")}),
        ("天数与窗口", {"fields": ("auto_close_reminder_days", "auto_close_days", "gallery_upload_window_days", "review_window_days")}),
        ("阈值", {"fields": ("gm_auto_promote_threshold", "like_level_publish_threshold", "anon_throttle_per_minute")}),
        (
            "赞级别五档边界（分母 = 赞 + 倒赞 + 无评价；前两项看赞占比，后两项看倒赞占比，都达不到即中性）",
            {"fields": ("level_overwhelmingly_positive_min", "level_mostly_positive_min", "level_overwhelmingly_negative_dislike_min", "level_mostly_negative_dislike_min")},
        ),
        ("预设与文案", {"fields": ("rule_system_presets", "site_name", "announcement", "icp_beian", "footer_tagline")}),
        (
            "首页第三、四段（内容与规则预设、快速选择在「站长内容」里改）",
            {"fields": ("home_section3_kicker", "home_section3_title", "home_section3_lead", "home_section4_kicker", "home_section4_title", "home_section4_lead")},
        ),
        ("首页精选照片", {"fields": ("featured_photos_enabled", "featured_photos_visibility")}),
    )

    #: 留成可编辑的话，站主在这里改完会在下次保存任一条预设时被静默覆盖。
    readonly_fields = ["rule_system_presets"]

    def has_add_permission(self, request) -> bool:
        return not SiteConfig.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def changelist_view(self, request, extra_context=None):
        """列表页直接跳到唯一那行的编辑页。"""
        from apps.siteconfig.services import get_config

        config = get_config()
        url = reverse("admin:siteconfig_siteconfig_change", args=[config.pk])
        return HttpResponseRedirect(url)
