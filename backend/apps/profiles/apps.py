from django.apps import AppConfig


class ProfilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.profiles"
    label = "profiles"
    verbose_name = "玩家卡与 GM 卡"

    def ready(self) -> None:
        from apps.profiles import signals  # noqa: F401
