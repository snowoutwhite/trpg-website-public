from django.urls import path

from apps.profiles.views import MyGMCardView, MyPlayerCardView, PublicProfileView

app_name = "profiles"

urlpatterns = [
    path("users/<int:user_id>/", PublicProfileView.as_view(), name="public-profile"),
    path("me/player-card/", MyPlayerCardView.as_view(), name="my-player-card"),
    path("me/gm-card/", MyGMCardView.as_view(), name="my-gm-card"),
]
