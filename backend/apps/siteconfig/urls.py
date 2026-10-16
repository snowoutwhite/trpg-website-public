from django.urls import path

from apps.siteconfig.views import PublicSiteConfigView

app_name = "siteconfig"

urlpatterns = [
    path("", PublicSiteConfigView.as_view(), name="detail"),
]
