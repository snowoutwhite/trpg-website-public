"""角色卡路由。前缀 /api/v1/charactercards/ 已在 config/urls.py 接好。"""

from django.urls import path

from apps.charactercards.views import (
    CardDetailView,
    CardDownloadView,
    CardPoolView,
    MyCardDetailView,
    MyCardFilesView,
    MyCardListCreateView,
)

app_name = "charactercards"

urlpatterns = [
    path("pool/", CardPoolView.as_view(), name="pool"),
    path("mine/", MyCardListCreateView.as_view(), name="my-cards"),
    path("mine/<int:pk>/", MyCardDetailView.as_view(), name="my-card-detail"),
    path("mine/<int:pk>/files/", MyCardFilesView.as_view(), name="my-card-files"),
    path("<int:pk>/", CardDetailView.as_view(), name="card-detail"),
    path("<int:pk>/download/", CardDownloadView.as_view(), name="card-download"),
]
