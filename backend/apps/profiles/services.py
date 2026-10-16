"""玩家卡 / GM 卡业务逻辑：建卡、重算统计、算档位。"""

from __future__ import annotations

from decimal import Decimal

from apps.profiles import levels, stats
from apps.profiles.models import GMCard, PlayerCard
from apps.siteconfig.services import get_config


def ensure_player_card(user) -> PlayerCard:
    card, _ = PlayerCard.objects.get_or_create(user=user)
    return card


def ensure_gm_card(user) -> GMCard:
    card, _ = GMCard.objects.get_or_create(user=user)
    return card


def level_for(like: int, dislike: int, total: int) -> str | None:
    """按赞占比 / 倒赞占比算五档。"""
    config = get_config()
    if not config.like_feature_enabled:
        return None
    if total < config.like_level_publish_threshold:
        return None
    if total <= 0:
        return None

    like_ratio = Decimal(like) / Decimal(total)
    dislike_ratio = Decimal(dislike) / Decimal(total)

    if like_ratio >= Decimal(config.level_overwhelmingly_positive_min):
        return levels.OVERWHELMINGLY_POSITIVE
    if like_ratio >= Decimal(config.level_mostly_positive_min):
        return levels.MOSTLY_POSITIVE
    if dislike_ratio >= Decimal(config.level_overwhelmingly_negative_dislike_min):
        return levels.OVERWHELMINGLY_NEGATIVE
    if dislike_ratio >= Decimal(config.level_mostly_negative_dislike_min):
        return levels.MOSTLY_NEGATIVE
    return levels.MIXED


def recompute_player_card(user) -> PlayerCard:
    """按已注册的 provider 重算玩家卡缓存字段。"""
    card = ensure_player_card(user)
    return _recompute(card, stats.collect_player_stats(user))


def recompute_gm_card(user) -> GMCard:
    """按已注册的 provider 重算 GM 卡缓存字段。"""
    card = ensure_gm_card(user)
    return _recompute(card, stats.collect_gm_stats(user))


def _recompute(card, collected: dict):
    changed = []
    for key, value in collected.items():
        if getattr(card, key, None) != value:
            setattr(card, key, value)
            changed.append(key)

    new_level = level_for(card.likes, card.dislikes, card.reviews_received) or ""
    if card.level != new_level:
        card.level = new_level
        changed.append("level")

    if changed:
        card.save(update_fields=[*changed, "updated_at"])
    return card
