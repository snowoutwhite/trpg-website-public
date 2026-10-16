"""团路由。前缀 /api/v1/games/ 已在 config/urls.py 接好。

注意顺序：`tags/` 与 `my-signups/` 必须排在 `<int:pk>/` 之前（它们不是数字，其实不会撞，
但显式排前面更稳）。
"""

from django.urls import path

from apps.games.views import (
    GameCancelView,
    GameDetailView,
    GameExpandView,
    GameFinishView,
    GameListCreateView,
    GameRecruitingRosterView,
    GameRosterView,
    GameSignupView,
    GameStartView,
    GameSubmitCardView,
    GameWithdrawView,
    MySignupListView,
    SessionDetailView,
    SessionListCreateView,
    SignupConfirmWithdrawView,
    SignupRemoveView,
    SignupReviewView,
    SignupUploadCardView,
    TagListView,
)

app_name = "games"

urlpatterns = [
    path("", GameListCreateView.as_view(), name="list"),
    path("tags/", TagListView.as_view(), name="tags"),
    path("my-signups/", MySignupListView.as_view(), name="my-signups"),
    path("<int:pk>/", GameDetailView.as_view(), name="detail"),
    # 名单两段式
    path("<int:pk>/signups/", GameRecruitingRosterView.as_view(), name="recruiting-roster"),
    path("<int:pk>/roster/", GameRosterView.as_view(), name="roster"),
    # PL 侧
    path("<int:pk>/signup/", GameSignupView.as_view(), name="signup"),
    path("<int:pk>/withdraw/", GameWithdrawView.as_view(), name="withdraw"),
    path("<int:pk>/submit-card/", GameSubmitCardView.as_view(), name="submit-card"),
    # GM 侧
    path("<int:pk>/expand/", GameExpandView.as_view(), name="expand"),
    path("<int:pk>/start/", GameStartView.as_view(), name="start"),
    path("<int:pk>/finish/", GameFinishView.as_view(), name="finish"),
    path("<int:pk>/cancel/", GameCancelView.as_view(), name="cancel"),
    path("<int:pk>/signups/<int:signup_id>/review/", SignupReviewView.as_view(), name="signup-review"),
    path(
        "<int:pk>/signups/<int:signup_id>/upload-card/",
        SignupUploadCardView.as_view(),
        name="signup-upload-card",
    ),
    path("<int:pk>/signups/<int:signup_id>/remove/", SignupRemoveView.as_view(), name="signup-remove"),
    path(
        "<int:pk>/signups/<int:signup_id>/confirm-withdraw/",
        SignupConfirmWithdrawView.as_view(),
        name="signup-confirm-withdraw",
    ),
    # 场次
    path("<int:pk>/sessions/", SessionListCreateView.as_view(), name="sessions"),
    path("<int:pk>/sessions/<int:session_id>/", SessionDetailView.as_view(), name="session-detail"),
]
