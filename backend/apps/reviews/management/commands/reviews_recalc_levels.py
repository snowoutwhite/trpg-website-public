"""一次性重算全部玩家卡 / GM 卡的团次数、被评次数、赞 / 倒赞与赞级别。

给存量数据用：

    cd backend && uv run python manage.py reviews_recalc_levels

幂等，可重复跑；日常不需要 —— 每小时的 `reviews_window_closing` 会在评价窗口关闭后
自动重算受影响的人。
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.reviews.services import recalc_all_cards


class Command(BaseCommand):
    help = "重算全部玩家卡与 GM 卡（含「无评价」计入被评次数与赞级别）"

    def handle(self, *args, **options) -> None:
        result = recalc_all_cards()
        self.stdout.write("玩家卡={player_cards} GM 卡={gm_cards}".format(**result))
