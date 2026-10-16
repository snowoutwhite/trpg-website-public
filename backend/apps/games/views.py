"""团的接口。视图只做鉴权、取对象、序列化；业务规则全在 `services.py`。"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.charactercards.models import CharacterCard
from apps.games import services
from apps.games.models import MODE_CHOICES, Game, Session, Signup, Tag
from apps.games.serializers import (
    ConfirmWithdrawInputSerializer,
    ExpandInputSerializer,
    FinishInputSerializer,
    GameDetailSerializer,
    GameListSerializer,
    GameWriteSerializer,
    GMSignupSerializer,
    GMUploadCardInputSerializer,
    MySignupSerializer,
    ReasonInputSerializer,
    RecruitingSignupSerializer,
    ReviewInputSerializer,
    RosterSignupSerializer,
    SessionSerializer,
    SubmitCardInputSerializer,
    TagSerializer,
    WithdrawInputSerializer,
)
from apps.siteconfig.services import OTHER_SENTINEL, exclude_preset_rule_systems
from common.exceptions import AccountBanned, AccountDeactivated, ApiError
from common.pagination import StandardPagination
from common.permissions import IsAuthenticatedAndActive, IsNotMuted


class LoginRequired(ApiError):
    """显式 401：会话认证下 DRF 会把 NotAuthenticated 降级成 403，这里要区分开。"""

    status_code = http_status.HTTP_401_UNAUTHORIZED
    default_code = "not_authenticated"
    default_detail = "请先登录。"


def _require_active_login(request: Request) -> None:
    """名单是登录内容：游客 401，封禁/注销号 403。

    口径对齐 `common.permissions.IsAuthenticatedAndActive` 与 charactercards 的
    `can_view_file`：写接口挡住的账号，读私密内容的口子不能更松。
    """
    user = request.user
    if not getattr(user, "is_authenticated", False):
        raise LoginRequired()
    # 封禁会同时置 is_active=False，所以先判封禁（缺陷 D4：code 要认得出是哪一种）
    if getattr(user, "is_banned", False):
        raise AccountBanned()
    if not user.is_active:
        raise AccountDeactivated()


def _get_game(pk: int) -> Game:
    return get_object_or_404(
        Game.objects.select_related("gm", "campaign_prev").prefetch_related("tags", "sessions"), pk=pk
    )


class _GMActionMixin:
    """GM 侧动作的公共部分：必须是本团 GM。

    禁言只禁「放团 / 报名 / 评价」，
    所以团内管理动作用 `IsAuthenticatedAndActive` 而不是 `IsNotMuted`。
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get_game(self, request: Request, pk: int) -> Game:
        game = _get_game(pk)
        if not services.is_game_gm(request.user, game):
            raise services.NotGameGM()
        return game

    def get_signup(self, request: Request, pk: int, signup_id: int) -> Signup:
        game = self.get_game(request, pk)
        return get_object_or_404(
            Signup.objects.select_related("player", "game", "card"), pk=signup_id, game=game
        )


# --------------------------------------------------------------------------
# 团：列表 / 详情 / 放团 / 改团
# --------------------------------------------------------------------------


#: 招募列表允许的排序值 —— **白名单，不是「把参数塞进 order_by」**。
#: 放开任意字段等于给出一条排序信道：按 `gm__email` 排能二分出别人的邮箱，
#: 按 `signups__id` 排能推出报名先后，按任何隐私字段排都能一点点问出它的值。
#: 这里只留三种前端真的要用的顺序，其余一律回落到默认。
GAME_ORDERING_WHITELIST = {
    "start_at": ("start_at", "id"),
    "-start_at": ("-start_at", "-id"),
    "-created_at": ("-created_at", "-id"),
}
GAME_ORDERING_DEFAULT = "-created_at"

#: `?mode=` 认得的值，直接取模型 choices，免得模型加一种开团方式这里还得跟着改。
GAME_MODES = frozenset(value for value, _label in MODE_CHOICES)


class GameListCreateView(APIView):
    """GET /api/v1/games/（游客可读，?tag=&status=&rule_system=&mode=&gm=&ordering=）"""

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsNotMuted()]
        return [AllowAny()]

    def get(self, request: Request) -> Response:
        queryset = Game.objects.select_related("gm").prefetch_related("tags")
        params = request.query_params
        # 惰性刷新：到点的团在被列出来之前就进入「进行中」。
        services.refresh_due_games(queryset)

        tag = params.get("tag", "").strip()
        if tag == OTHER_SENTINEL:
            # 「其他」= 一枚预设标签都没挂的团。`exclude` 作用在多值关系上就是
            # 「不存在任何一条满足条件的关联行」，正好是这个意思。
            queryset = queryset.exclude(tags__is_preset=True)
        elif tag:
            queryset = queryset.filter(tags__name=tag)
        game_status = params.get("status", "").strip()
        if game_status:
            queryset = queryset.filter(status=game_status)
        rule_system = params.get("rule_system", "").strip()
        if rule_system == OTHER_SENTINEL:
            # 「其他」= 规则名不命中任何一条站级预设（大小写不敏感），规则名为空也算。
            queryset = exclude_preset_rule_systems(queryset)
        elif rule_system:
            queryset = queryset.filter(rule_system__iexact=rule_system)
        mode = params.get("mode", "").strip()
        if mode in GAME_MODES:
            queryset = queryset.filter(mode=mode)
        gm_id = params.get("gm", "").strip()
        if gm_id.isdigit():
            queryset = queryset.filter(gm_id=int(gm_id))

        # 排序只认白名单；认不出的值静默回落到默认顺序（不报错，前端老版本不会炸）。
        ordering = params.get("ordering", "").strip()
        fields = GAME_ORDERING_WHITELIST.get(ordering) or GAME_ORDERING_WHITELIST[
            GAME_ORDERING_DEFAULT
        ]
        queryset = queryset.order_by(*fields)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset.distinct(), request, view=self)
        serializer = GameListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request: Request) -> Response:
        serializer = GameWriteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tags = data.pop("tags", None)
        game = services.create_game(request.user, tags=tags, **data)
        return Response(
            GameDetailSerializer(game, context={"request": request}).data,
            status=http_status.HTTP_201_CREATED,
        )


class GameDetailView(APIView):
    """GET /api/v1/games/<pk>/（游客可读公告 + GM 面板）
    PATCH /api/v1/games/<pk>/（本团 GM 改公告）
    """

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsAuthenticatedAndActive()]
        return [AllowAny()]

    def get(self, request: Request, pk: int) -> Response:
        game = _get_game(pk)
        services.refresh_game(game)
        return Response(GameDetailSerializer(game, context={"request": request}).data)

    def patch(self, request: Request, pk: int) -> Response:
        game = _get_game(pk)
        if not services.is_game_gm(request.user, game):
            raise services.NotGameGM()
        serializer = GameWriteSerializer(
            game, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tags = data.pop("tags", None)
        game = services.update_game(game, tags=tags, **data)
        return Response(GameDetailSerializer(game, context={"request": request}).data)


# --------------------------------------------------------------------------
# 名单（两段式）
# --------------------------------------------------------------------------


class GameRecruitingRosterView(APIView):
    """GET /api/v1/games/<pk>/signups/ —— 招募中名单，登录用户可见，含报名顺序。"""

    permission_classes = [AllowAny]

    def get(self, request: Request, pk: int) -> Response:
        _require_active_login(request)
        game = _get_game(pk)
        records = services.recruiting_roster(game)
        return Response(
            {
                "count": records.count(),
                "accepted_count": game.accepted_count,
                "max_players": game.max_players,
                "results": RecruitingSignupSerializer(records, many=True).data,
            }
        )


class GameRosterView(APIView):
    """GET /api/v1/games/<pk>/roster/ —— 正式名单，只给同团；GM 另见卡与审批栏。"""

    permission_classes = [AllowAny]

    def get(self, request: Request, pk: int) -> Response:
        _require_active_login(request)
        game = _get_game(pk)
        if services.is_game_gm(request.user, game):
            records = services.gm_roster(game)
            return Response({"is_gm": True, "results": GMSignupSerializer(records, many=True).data})
        if not services.is_team_member(request.user, game):
            raise PermissionDenied("正式名单只对同团成员可见")
        records = services.accepted_roster(game)
        return Response({"is_gm": False, "results": RosterSignupSerializer(records, many=True).data})


# --------------------------------------------------------------------------
# PL 侧动作
# --------------------------------------------------------------------------


class GameSignupView(APIView):
    """POST /api/v1/games/<pk>/signup/"""

    permission_classes = [IsNotMuted]

    def post(self, request: Request, pk: int) -> Response:
        game = _get_game(pk)
        record = services.signup(game, request.user)
        return Response(
            MySignupSerializer(record).data, status=http_status.HTTP_201_CREATED
        )


class GameWithdrawView(APIView):
    """POST /api/v1/games/<pk>/withdraw/ —— 截止前直接退，截止后转成待 GM 确认的申请。"""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request, pk: int) -> Response:
        game = _get_game(pk)
        serializer = WithdrawInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = get_object_or_404(Signup, game=game, player=request.user)
        result = services.withdraw(record, reason=serializer.validated_data.get("reason", ""))
        record.refresh_from_db()
        return Response({**result, "signup": MySignupSerializer(record).data})


class GameSubmitCardView(APIView):
    """POST /api/v1/games/<pk>/submit-card/ —— 交卡（只能交自己的、尚存的卡）。"""

    permission_classes = [IsNotMuted]

    def post(self, request: Request, pk: int) -> Response:
        game = _get_game(pk)
        serializer = SubmitCardInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = get_object_or_404(Signup, game=game, player=request.user)
        # 按 owner 过滤：别人的卡直接 404，不泄露「这个 id 存在」。
        card = get_object_or_404(
            CharacterCard, pk=serializer.validated_data["card_id"], owner=request.user
        )
        record = services.submit_card(record, card)
        return Response(MySignupSerializer(record).data)


class MySignupListView(APIView):
    """GET /api/v1/games/my-signups/ —— 我的报名（只有本人自己的记录）。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        queryset = (
            Signup.objects.filter(player=request.user)
            .select_related("game", "card")
            .order_by("-created_at")
        )
        game_status = request.query_params.get("game_status", "").strip()
        if game_status:
            queryset = queryset.filter(game__status=game_status)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(MySignupSerializer(page, many=True).data)


# --------------------------------------------------------------------------
# GM 侧动作
# --------------------------------------------------------------------------


class SignupReviewView(_GMActionMixin, APIView):
    """POST /api/v1/games/<pk>/signups/<signup_id>/review/ —— 通过 / 驳回。"""

    def post(self, request: Request, pk: int, signup_id: int) -> Response:
        record = self.get_signup(request, pk, signup_id)
        serializer = ReviewInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.review_signup(
            record,
            approved=serializer.validated_data["approved"],
            note=serializer.validated_data.get("note", ""),
        )
        return Response(GMSignupSerializer(record).data)


class SignupUploadCardView(_GMActionMixin, APIView):
    """POST /api/v1/games/<pk>/signups/<signup_id>/upload-card/ —— GM 代 PL 传卡并通过。"""

    throttle_classes = [UserRateThrottle, ScopedRateThrottle]
    throttle_scope = "upload"

    def post(self, request: Request, pk: int, signup_id: int) -> Response:
        record = self.get_signup(request, pk, signup_id)
        serializer = GMUploadCardInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.gm_upload_card(
            record,
            serializer.validated_data["file"],
            gm=request.user,
            name=serializer.validated_data.get("name", ""),
            rule_system=serializer.validated_data.get("rule_system", ""),
            note=serializer.validated_data.get("note", ""),
        )
        return Response(GMSignupSerializer(record).data, status=http_status.HTTP_201_CREATED)


class SignupRemoveView(_GMActionMixin, APIView):
    """POST /api/v1/games/<pk>/signups/<signup_id>/remove/ —— 必须写理由。"""

    def post(self, request: Request, pk: int, signup_id: int) -> Response:
        record = self.get_signup(request, pk, signup_id)
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.gm_remove(record, reason=serializer.validated_data["reason"])
        return Response(GMSignupSerializer(record).data)


class SignupConfirmWithdrawView(_GMActionMixin, APIView):
    """POST /api/v1/games/<pk>/signups/<signup_id>/confirm-withdraw/"""

    def post(self, request: Request, pk: int, signup_id: int) -> Response:
        record = self.get_signup(request, pk, signup_id)
        serializer = ConfirmWithdrawInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.confirm_withdraw(
            record,
            approved=serializer.validated_data.get("approved", True),
            note=serializer.validated_data.get("note", ""),
        )
        return Response(GMSignupSerializer(record).data)


class GameExpandView(_GMActionMixin, APIView):
    """POST /api/v1/games/<pk>/expand/ —— 扩容，满员关闭的报名会重新开放。"""

    def post(self, request: Request, pk: int) -> Response:
        game = self.get_game(request, pk)
        serializer = ExpandInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        game = services.expand_capacity(game, max_players=serializer.validated_data["max_players"])
        return Response(GameDetailSerializer(game, context={"request": request}).data)


class GameStartView(_GMActionMixin, APIView):
    """POST /api/v1/games/<pk>/start/"""

    def post(self, request: Request, pk: int) -> Response:
        game = services.start_game(self.get_game(request, pk))
        return Response(GameDetailSerializer(game, context={"request": request}).data)


class GameFinishView(_GMActionMixin, APIView):
    """POST /api/v1/games/<pk>/finish/ —— 结团，body 必须给到场名单。"""

    def post(self, request: Request, pk: int) -> Response:
        game = self.get_game(request, pk)
        serializer = FinishInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        game = services.finish_game(
            game, attended_signup_ids=serializer.validated_data["attended_signup_ids"]
        )
        return Response(GameDetailSerializer(game, context={"request": request}).data)


class GameCancelView(_GMActionMixin, APIView):
    """POST /api/v1/games/<pk>/cancel/ —— 必须写理由；取消团不计任何次数。"""

    def post(self, request: Request, pk: int) -> Response:
        game = self.get_game(request, pk)
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        game = services.cancel_game(game, reason=serializer.validated_data["reason"])
        return Response(GameDetailSerializer(game, context={"request": request}).data)


# --------------------------------------------------------------------------
# 场次（首发只做 CRUD）
# --------------------------------------------------------------------------


class SessionListCreateView(APIView):
    """GET（游客可读）/ POST（本团 GM）/api/v1/games/<pk>/sessions/"""

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticatedAndActive()]
        return [AllowAny()]

    def get(self, request: Request, pk: int) -> Response:
        game = _get_game(pk)
        return Response({"results": SessionSerializer(game.sessions.all(), many=True).data})

    def post(self, request: Request, pk: int) -> Response:
        game = _get_game(pk)
        if not services.is_game_gm(request.user, game):
            raise services.NotGameGM()
        serializer = SessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.create_session(
            game,
            index=serializer.validated_data.get("index", 0),
            label=serializer.validated_data.get("label", ""),
            held_at=serializer.validated_data.get("held_at"),
        )
        return Response(SessionSerializer(session).data, status=http_status.HTTP_201_CREATED)


class SessionDetailView(_GMActionMixin, APIView):
    """GET/PATCH/DELETE /api/v1/games/<pk>/sessions/<session_id>/ —— 改删只有本团 GM。"""

    permission_classes = [IsAuthenticatedAndActive]

    def _get_session(self, request: Request, pk: int, session_id: int) -> Session:
        game = self.get_game(request, pk)
        return get_object_or_404(Session, pk=session_id, game=game)

    def get(self, request: Request, pk: int, session_id: int) -> Response:
        return Response(SessionSerializer(self._get_session(request, pk, session_id)).data)

    def patch(self, request: Request, pk: int, session_id: int) -> Response:
        session = self._get_session(request, pk, session_id)
        serializer = SessionSerializer(session, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        session = services.update_session(session, **serializer.validated_data)
        return Response(SessionSerializer(session).data)

    def delete(self, request: Request, pk: int, session_id: int) -> Response:
        session = self._get_session(request, pk, session_id)
        session.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# 标签
# --------------------------------------------------------------------------


class TagListView(APIView):
    """GET /api/v1/games/tags/?q=&page=&page_size= —— 标签列表/搜索，预设标签排在前面。

    标签是 GM 自由输入 + `get_or_create` 的全站共享命名空间，会随着放团数量无上限增长，
    所以**分页**（W5）：原来是硬截断 `[:50]`，第 51 个标签之后谁也翻不到，
    前端的「选已有标签」下拉从此看不见新标签。`?q=` 仍然是服务端模糊搜索。
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        queryset = Tag.objects.all()
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(name__icontains=keyword)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(TagSerializer(page, many=True).data)
