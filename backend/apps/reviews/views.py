"""团后评价的接口。视图只做鉴权、取对象、序列化；规则全在 `services.py`。

| 方法 + 路径 | 权限 | 匿名性 |
|---|---|---|
| `POST /api/v1/reviews/` | 登录 + 未禁言 + 本团到场 | 写入，upsert |
| `GET /api/v1/reviews/pending/` | 登录 | 本人待评对象 |
| `GET /api/v1/reviews/mine/given/` | 登录 | 本人发出的，带 reviewee |
| `GET /api/v1/reviews/mine/received/` | 登录 | **匿名 + 延迟 + 打乱顺序** |
| `GET /api/v1/reviews/games/<id>/mutual/` | 登录 + 本团到场 | 互见，同样匿名 |
| `GET /api/v1/reviews/quota/` | 登录 | 本人配额统计 |

所有接口都只作用于**当前登录者**：没有任何一个入口接受「看别人的评价」的参数。
禁言只禁「放团 / 报名 / 评价」，所以只有写入用 `IsNotMuted`。
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.games.models import Game
from apps.reviews import services
from apps.reviews.serializers import (
    AnonymousReviewSerializer,
    GivenReviewSerializer,
    MutualGroupSerializer,
    PendingGameSerializer,
    ReviewGameSerializer,
    ReviewWriteSerializer,
)
from common.permissions import IsAuthenticatedAndActive, IsNotMuted


class ReviewCreateView(APIView):
    """POST /api/v1/reviews/ —— 创建或修改一条评价（窗口内可改，不可撤回）。"""

    permission_classes = [IsNotMuted]

    def post(self, request: Request) -> Response:
        serializer = ReviewWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        review, created = services.upsert_review(
            request.user,
            game=data["game"],
            reviewee=data["reviewee"],
            verdict=data["verdict"],
            text=data["text"],
        )
        return Response(
            GivenReviewSerializer(review).data,
            status=http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK,
        )


class PendingReviewView(APIView):
    """GET /api/v1/reviews/pending/ —— 已结团、在窗口内、本人还没评的对象。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        pending = services.pending_for(request.user)
        return Response({"results": PendingGameSerializer(pending, many=True).data})


class MyGivenReviewsView(APIView):
    """GET /api/v1/reviews/mine/given/ —— 本人发出的评价。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        reviews = services.given_by(request.user)
        return Response({"results": GivenReviewSerializer(reviews, many=True).data})


class MyReceivedReviewsView(APIView):
    """GET /api/v1/reviews/mine/received/ —— 本人收到的评价。

    匿名、延迟、顺序打乱三条规则都在 `services.received_by` 里，
    这里只负责把结果塞进白名单序列化器。
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        visible, hidden = services.received_by(request.user)
        return Response(
            {
                "results": AnonymousReviewSerializer(visible, many=True).data,
                # 「尚不可见」只给一个计数，不给团、不给时间，也不给条目本身。
                "hidden_count": hidden,
                "visible_after_games": services.visible_after_games(),
            }
        )


class GameMutualReviewsView(APIView):
    """GET /api/v1/reviews/games/<id>/mutual/ —— 评价互见。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request, game_id: int) -> Response:
        game = get_object_or_404(Game.objects.select_related("gm"), pk=game_id)
        result = services.mutual_for(request.user, game)
        return Response(
            {
                "game": ReviewGameSerializer(result["game"]).data,
                "available": result["available"],
                "visible_after_games": services.visible_after_games(),
                "groups": MutualGroupSerializer(result["groups"], many=True).data,
            }
        )


class ReviewQuotaView(APIView):
    """GET /api/v1/reviews/quota/ —— 配额 = Σ(各团人数 − 1)，只给本人看。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        return Response(services.quota_for(request.user))
