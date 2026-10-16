"""站级配置对外序列化。

隐私约定：这个接口对游客开放，只暴露前端渲染需要的字段。
运维类参数（自动结团天数、五档边界、更新时间）一律不外露。
"""

from rest_framework import serializers

from apps.siteconfig.models import SiteConfig


class PublicSiteConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteConfig
        fields = [
            "site_name",
            "announcement",
            "icp_beian",
            "footer_tagline",
            "like_feature_enabled",
            "invite_code_required",
            "gallery_moderation_mode",
            "rule_system_presets",
            "like_level_publish_threshold",
            "review_window_days",
            "gallery_upload_window_days",
            "gm_auto_promote_threshold",
        ]
        read_only_fields = fields
