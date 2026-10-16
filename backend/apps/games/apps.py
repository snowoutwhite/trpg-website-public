from django.apps import AppConfig


class GamesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.games"
    label = "games"
    verbose_name = "团"

    def ready(self) -> None:
        """业务规则与安全约束。"""
        from apps.charactercards.services import (
            register_file_access_checker,
            register_play_detail_provider,
        )
        from apps.games import services
        from apps.profiles.stats import (
            register_gm_stats_provider,
            register_player_stats_provider,
        )

        register_player_stats_provider(services.player_stats_provider)
        register_gm_stats_provider(services.gm_stats_provider)
        register_file_access_checker(services.gm_can_view_submitted_card)
        register_play_detail_provider(services.play_detail_provider)
