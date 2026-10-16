"""全站路由。

约定：
- 业务接口一律挂在 `/api/v1/<app>/` 下，每个 app 自己维护 `urls.py`。
- allauth headless（browser 客户端）挂在 `/_allauth/`，前端直接调它做注册/登录/验证邮箱/重置密码。
- 后台路径从环境变量 `DJANGO_ADMIN_URL` 读，默认不是 /admin/。
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from common.views import deny_protected_media, health

api_v1_patterns = [
    path("health/", health, name="health"),
    path("siteconfig/", include("apps.siteconfig.urls")),
    path("home/", include("apps.homecontent.urls")),
    path("announcements/", include("apps.homecontent.announcement_urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("profiles/", include("apps.profiles.urls")),
    path("content/", include("apps.content.urls")),
    path("resources/", include("apps.resources.urls")),
    path("charactercards/", include("apps.charactercards.urls")),
    path("games/", include("apps.games.urls")),
    path("reviews/", include("apps.reviews.urls")),
    path("gallery/", include("apps.gallery.urls")),
    path("reports/", include("apps.reports.urls")),
    path("points/", include("apps.points.urls")),
    path("notifications/", include("apps.notifications.urls")),
]

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("_allauth/", include("allauth.headless.urls")),
    path("api/v1/", include((api_v1_patterns, "api"), namespace="v1")),
]

if settings.DEBUG:
    # 开发期由 Django 直出公开媒体；生产由 Nginx 接管，受保护文件永远走鉴权视图。
    # 顺序要紧：先把 protected/ 堵死，再挂 static()，否则私密文件会被直接下载走。
    protected_url = settings.MEDIA_URL.lstrip("/") + settings.PROTECTED_MEDIA_DIRNAME + "/"
    urlpatterns += [re_path(rf"^{protected_url}", deny_protected_media)]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
