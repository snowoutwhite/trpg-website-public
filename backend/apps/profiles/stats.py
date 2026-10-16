"""卡片统计的来源注册表。

`profiles` 不认识 `games` 与 `reviews`（它们后开发），所以反过来：
那两个 app 在自己的 `AppConfig.ready()` 里注册一个 provider，
`recompute_player_card` / `recompute_gm_card` 调用时依次合并各 provider 的返回值。

provider 约定：
    def provider(user) -> dict
玩家卡可返回的键：games_played / reviews_received / likes / dislikes
GM 卡可返回的键：games_hosted / reviews_received / likes / dislikes
未返回的键保持原值不变。
"""

from __future__ import annotations

from collections.abc import Callable

PlayerStatsProvider = Callable[[object], dict]
GMStatsProvider = Callable[[object], dict]

_player_providers: list[PlayerStatsProvider] = []
_gm_providers: list[GMStatsProvider] = []

PLAYER_STAT_KEYS = ("games_played", "reviews_received", "likes", "dislikes")
GM_STAT_KEYS = ("games_hosted", "reviews_received", "likes", "dislikes")


def register_player_stats_provider(provider: PlayerStatsProvider) -> None:
    if provider not in _player_providers:
        _player_providers.append(provider)


def register_gm_stats_provider(provider: GMStatsProvider) -> None:
    if provider not in _gm_providers:
        _gm_providers.append(provider)


def collect_player_stats(user) -> dict:
    return _collect(_player_providers, user, PLAYER_STAT_KEYS)


def collect_gm_stats(user) -> dict:
    return _collect(_gm_providers, user, GM_STAT_KEYS)


def _collect(providers, user, allowed_keys: tuple[str, ...]) -> dict:
    merged: dict = {}
    for provider in providers:
        result = provider(user) or {}
        for key, value in result.items():
            if key in allowed_keys:
                merged[key] = value
    return merged
