"""公告历史页的路由：`/api/v1/announcements/`。

单独一个模块而不是挂在 `home/` 下面，是因为实施方案把它定成了一个独立的顶层资源
（首页只给最新一条，历史列表是另一个页面）。反查名 `v1:announcements:list`。
"""

from django.urls import path

from apps.homecontent.views import AnnouncementListView

app_name = "announcements"

urlpatterns = [
    path("", AnnouncementListView.as_view(), name="list"),
]
