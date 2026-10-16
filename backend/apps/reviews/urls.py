"""团后评价路由。前缀 /api/v1/reviews/ 已在 config/urls.py 接好。

注意：没有「按用户查评价」的路径。所有读取入口都只回当前登录者自己的数据，
互见面板也必须是本团到场成员才进得去。
"""

from django.urls import path

from apps.reviews.views import (
    GameMutualReviewsView,
    MyGivenReviewsView,
    MyReceivedReviewsView,
    PendingReviewView,
    ReviewCreateView,
    ReviewQuotaView,
)

app_name = "reviews"

urlpatterns = [
    path("", ReviewCreateView.as_view(), name="create"),
    path("pending/", PendingReviewView.as_view(), name="pending"),
    path("quota/", ReviewQuotaView.as_view(), name="quota"),
    path("mine/given/", MyGivenReviewsView.as_view(), name="mine-given"),
    path("mine/received/", MyReceivedReviewsView.as_view(), name="mine-received"),
    path("games/<int:game_id>/mutual/", GameMutualReviewsView.as_view(), name="game-mutual"),
]
