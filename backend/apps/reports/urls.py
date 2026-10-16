"""战报路由。前缀 /api/v1/reports/ 已在 config/urls.py 接好。"""

from django.urls import path

from apps.reports.views import (
    AttachmentDownloadView,
    FeaturedReportListView,
    ReportAbuseView,
    ReportAttachmentDetailView,
    ReportAttachmentListView,
    ReportDetailView,
    ReportDocumentImportView,
    ReportListCreateView,
)

app_name = "reports"

urlpatterns = [
    path("", ReportListCreateView.as_view(), name="report-list"),
    path("featured/", FeaturedReportListView.as_view(), name="report-featured"),
    path("import-document/", ReportDocumentImportView.as_view(), name="report-import-document"),
    path("<int:pk>/", ReportDetailView.as_view(), name="report-detail"),
    path("<int:pk>/attachments/", ReportAttachmentListView.as_view(), name="attachment-list"),
    path(
        "<int:pk>/attachments/<int:attachment_id>/",
        ReportAttachmentDetailView.as_view(),
        name="attachment-detail",
    ),
    path(
        "<int:pk>/attachments/<int:attachment_id>/download/",
        AttachmentDownloadView.as_view(),
        name="attachment-download",
    ),
    path("<int:pk>/report/", ReportAbuseView.as_view(), name="report-abuse"),
]
