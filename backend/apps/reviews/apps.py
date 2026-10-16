from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reviews"
    label = "reviews"
    verbose_name = "团后评价"

    def ready(self) -> None:
        """业务规则与安全约束。"""
        from apps.profiles.stats import (
            register_gm_stats_provider,
            register_player_stats_provider,
        )
        from apps.reviews import services

        register_player_stats_provider(services.player_review_stats_provider)
        register_gm_stats_provider(services.gm_review_stats_provider)
