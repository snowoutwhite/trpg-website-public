"""把规则预设表同步进 `SiteConfig.rule_system_presets` 只读镜像。

挂在本 app 而不是 siteconfig 里：siteconfig 是全站最底层的叶子模块，
不能反过来认识 homecontent（会做出导入环）。
"""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from apps.homecontent.models import RuleSystemPreset, SiteAnnouncement


@receiver(post_save, sender=RuleSystemPreset, dispatch_uid="homecontent_sync_presets_save")
def _sync_on_save(sender, instance, **kwargs) -> None:
    from apps.homecontent.services import sync_rule_system_presets

    sync_rule_system_presets()


@receiver(post_delete, sender=RuleSystemPreset, dispatch_uid="homecontent_sync_presets_delete")
def _sync_on_delete(sender, instance, **kwargs) -> None:
    from apps.homecontent.services import sync_rule_system_presets

    sync_rule_system_presets()


@receiver(pre_delete, sender=SiteAnnouncement, dispatch_uid="homecontent_retract_announcement")
def _retract_notifications_on_delete(sender, instance, **kwargs) -> None:
    """删公告 = 撤回：已推到每位用户通知里的那条一并删除。"""
    from django.contrib.contenttypes.models import ContentType

    from apps.notifications import events
    from apps.notifications.models import Notification

    Notification.objects.filter(
        event=events.SITE_ANNOUNCEMENT,
        target_content_type=ContentType.objects.get_for_model(SiteAnnouncement),
        target_object_id=instance.pk,
    ).delete()
