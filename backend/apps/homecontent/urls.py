"""站长内容路由。

前缀 `/api/v1/home/` 已在 `config/urls.py` 接好；公告历史页单独挂在
`/api/v1/announcements/`（见同目录的 `announcement_urls.py`）。

反查名形如 `v1:homecontent:home`。
"""

from django.urls import path

from apps.homecontent.views import (
    AdminAnnouncementDetailView,
    AdminAnnouncementListView,
    AdminConfigView,
    AdminFeaturedCandidateView,
    AdminFeaturePhotoView,
    AdminHomeView,
    AdminQuickEntryDetailView,
    AdminQuickEntryImageView,
    AdminQuickEntryListView,
    AdminRulePresetDetailView,
    AdminRulePresetImageView,
    AdminRulePresetListView,
    FeaturedPhotoFileView,
    HomeView,
)

app_name = "homecontent"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path(
        "featured-photos/<int:pk>/file/",
        FeaturedPhotoFileView.as_view(),
        name="featured-photo-file",
    ),
    # 站主侧（is_staff）
    path("admin/", AdminHomeView.as_view(), name="admin-home"),
    path("admin/config/", AdminConfigView.as_view(), name="admin-config"),
    path("admin/rule-presets/", AdminRulePresetListView.as_view(), name="admin-rule-presets"),
    path(
        "admin/rule-presets/<int:pk>/",
        AdminRulePresetDetailView.as_view(),
        name="admin-rule-preset-detail",
    ),
    path(
        "admin/rule-presets/<int:pk>/image/",
        AdminRulePresetImageView.as_view(),
        name="admin-rule-preset-image",
    ),
    path("admin/quick-entries/", AdminQuickEntryListView.as_view(), name="admin-quick-entries"),
    path(
        "admin/quick-entries/<int:pk>/",
        AdminQuickEntryDetailView.as_view(),
        name="admin-quick-entry-detail",
    ),
    path(
        "admin/quick-entries/<int:pk>/image/",
        AdminQuickEntryImageView.as_view(),
        name="admin-quick-entry-image",
    ),
    path(
        "admin/announcements/", AdminAnnouncementListView.as_view(), name="admin-announcements"
    ),
    path(
        "admin/announcements/<int:pk>/",
        AdminAnnouncementDetailView.as_view(),
        name="admin-announcement-detail",
    ),
    path("admin/featured-photos/", AdminFeaturePhotoView.as_view(), name="admin-featured-photos"),
    path(
        "admin/featured-photos/candidates/",
        AdminFeaturedCandidateView.as_view(),
        name="admin-featured-candidates",
    ),
]