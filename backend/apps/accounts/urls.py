from django.urls import path

from apps.accounts.views import (
    AvatarView,
    DeactivateView,
    GMApplicationView,
    MeView,
    NicknameView,
)

app_name = "accounts"

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("me/nickname/", NicknameView.as_view(), name="nickname"),
    path("me/avatar/", AvatarView.as_view(), name="avatar"),
    path("me/gm-application/", GMApplicationView.as_view(), name="gm-application"),
    path("me/deactivate/", DeactivateView.as_view(), name="deactivate"),
]
