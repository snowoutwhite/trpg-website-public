"""建卡信号。"""

from __future__ import annotations

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.profiles.services import ensure_gm_card, ensure_player_card


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="profiles_ensure_cards")
def ensure_cards(sender, instance, created, **kwargs) -> None:
    if created:
        ensure_player_card(instance)
    if instance.is_gm:
        ensure_gm_card(instance)
