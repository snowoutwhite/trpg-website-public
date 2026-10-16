from django.urls import path

from apps.resources.views import (
    ResourceCategoryListView,
    ResourceDetailView,
    ResourceDownloadView,
    ResourceListCreateView,
)

app_name = "resources"

urlpatterns = [
    path("", ResourceListCreateView.as_view(), name="list"),
    # 放在 <int:pk> 之前不必要（pk 是 int 转换器），但显式排在前面更直观。
    path("categories/", ResourceCategoryListView.as_view(), name="categories"),
    path("<int:pk>/", ResourceDetailView.as_view(), name="detail"),
    path("<int:pk>/download/", ResourceDownloadView.as_view(), name="download"),
]
