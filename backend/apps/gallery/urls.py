"""活动相册路由。前缀 /api/v1/gallery/ 已在 config/urls.py 接好。

反查名形如 `v1:gallery:photo-file`（序列化器拼三档 URL 时用的就是它）。
"""

from django.urls import path

from apps.gallery.views import (
    ApprovePhotoView,
    GamePhotoListView,
    HandleReportView,
    ModerationQueueView,
    MyReportListView,
    PhotoDetailView,
    PhotoFileView,
    PhotoReportView,
    RejectPhotoView,
)

app_name = "gallery"

urlpatterns = [
    path("games/<int:game_id>/photos/", GamePhotoListView.as_view(), name="game-photos"),
    path("photos/<int:pk>/", PhotoDetailView.as_view(), name="photo-detail"),
    path("photos/<int:pk>/file/", PhotoFileView.as_view(), name="photo-file"),
    path("photos/<int:pk>/report/", PhotoReportView.as_view(), name="photo-report"),
    path("reports/mine/", MyReportListView.as_view(), name="my-reports"),
    # 站主侧（权限位 gallery.moderate_photo）
    path("moderation/queue/", ModerationQueueView.as_view(), name="moderation-queue"),
    path(
        "moderation/photos/<int:pk>/approve/", ApprovePhotoView.as_view(), name="moderation-approve"
    ),
    path(
        "moderation/photos/<int:pk>/reject/", RejectPhotoView.as_view(), name="moderation-reject"
    ),
    path(
        "moderation/reports/<int:pk>/handle/",
        HandleReportView.as_view(),
        name="moderation-handle-report",
    ),
]
