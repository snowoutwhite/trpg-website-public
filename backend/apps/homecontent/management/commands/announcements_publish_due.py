"""预告到点后的补推。

给 cron 用（建议每小时一次，与 `games_autoclose` / `reviews_window_closing` 同频）：

    cd backend && uv run python manage.py announcements_publish_due

做的事：把「生效中 + 已到 `published_at` + 一轮都没推过（`notified_at` 为空）」的
公告各推一轮全站通知。**幂等**：推过的公告 `notified_at` 已落下，再跑多少遍都不会
重复轰炸（幂等锚见 `services.publish_announcement`）。

为什么需要它：`published_at` 在未来的公告是预告，建的时候当场不推；到点之后公告会
自己进公开列表，但那时早就没有写请求了 —— 没有这条命令，预告到点等于悄悄地谁也不通知。
（公开读路径 `/home/`、`/announcements/` 也会顺手补一轮，那是给没配 cron 的部署兜底，
不是替代品：没人访问的时段照样该把通知发出去。）
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.homecontent.services import publish_due_announcements


class Command(BaseCommand):
    help = "把已到发布时间但还没推送过的站长公告补推一轮（幂等）"

    def handle(self, *args, **options) -> None:
        published = publish_due_announcements()
        self.stdout.write(f"补推公告={published}")
