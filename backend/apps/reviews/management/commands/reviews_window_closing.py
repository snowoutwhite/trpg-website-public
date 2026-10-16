"""评价窗口即将关闭的提醒。

给 cron 用（建议每小时一次，和 games_autoclose 一起排）：

    cd backend && uv run python manage.py reviews_window_closing

做的事：找出评价窗口只剩 24 小时的团，给**还有人没评**的到场成员各发一条站内提醒，
每团只发一轮（靠 `ReviewWindowNotice` 去重）。赞功能被站主关闭时提醒整轮跳过。

同一轮还做第二件事：找出评价窗口**已经关闭**、还没处理过的团，重算全体到场成员的卡
（「无评价」在窗口关闭后才计入被评次数与赞级别，靠 `ReviewWindowClosure` 每团一次）。
这一步不受赞功能开关影响。

注意：本站**不为「收到评价」发通知** —— 通知的时间戳等于提交时间戳，
会把评价人的提交时序泄露给被评者。只有「评价开放」（games 结团时发）与本命令两个事件。
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.reviews.services import run_window_closed_cycle, run_window_closing_cycle


class Command(BaseCommand):
    help = "给评价窗口即将关闭的团发提醒；窗口已关闭的团重算到场成员的卡（均每团一次）"

    def handle(self, *args, **options) -> None:
        result = run_window_closing_cycle()
        self.stdout.write("团={games} 提醒={notified}".format(**result))
        closed = run_window_closed_cycle()
        self.stdout.write("窗口已关闭的团={games} 重算卡片={refreshed}".format(**closed))
