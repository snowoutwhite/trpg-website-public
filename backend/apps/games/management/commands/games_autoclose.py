"""团的定时维护：状态刷新 + 三种提醒 + 自动结团。"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.games.services import run_autoclose_cycle


class Command(BaseCommand):
    help = "刷新团状态、发交卡/开团/结团提醒、按站点配置自动结团"

    def handle(self, *args, **options) -> None:
        result = run_autoclose_cycle()
        self.stdout.write(
            "进行中={refreshed} 交卡提醒={card_deadline_reminders} 开团提醒={start_reminders} "
            "结团提醒={close_reminders} 自动结团={auto_closed} 未交卡标记={no_card_marked}".format(
                **result
            )
        )
