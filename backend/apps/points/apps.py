from django.apps import AppConfig


class PointsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.points"
    label = "points"
    verbose_name = "积分与称号"
