from django.apps import AppConfig


class HomecontentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.homecontent"
    label = "homecontent"
    verbose_name = "站长内容"

    def ready(self) -> None:
        """把「规则预设表 → SiteConfig.rule_system_presets 只读镜像」的同步接上。

        siteconfig 是全站最底层的叶子模块（人人都 import 它），所以反向依赖只能
        由本 app 在启动时挂 signal，不能让 siteconfig 去 import homecontent。
        导入放在函数内部，避免 AppRegistryNotReady。
        """
        from apps.homecontent import signals  # noqa: F401
