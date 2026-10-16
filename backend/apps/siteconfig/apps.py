from django.apps import AppConfig


class SiteconfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.siteconfig"
    label = "siteconfig"
    verbose_name = "站点配置"
