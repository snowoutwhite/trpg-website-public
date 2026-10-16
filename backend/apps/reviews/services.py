"""团后评价的业务逻辑。视图只做鉴权与序列化，规则全部落在这里。"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.games.models import (
    GAME_FINISHED,
    SIGNUP_ACCEPTED,
    Game,
    Signup,
)
from apps.reviews.models import (
    ROLE_GM,
    ROLE_PL,
    VERDICT_DISLIKE,
    VERDICT_LIKE,
    Review,
)
from apps.siteconfig.services import get_config
from common.exceptions import ApiError, Forbidden

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

#: 延迟可见的团数。
#: **siteconfig 目前没有对应字段**（第 28 项的配置清单里没有这一条），所以取常量；
#: 一旦 siteconfig 加了 `review_visible_after_games`，`visible_after_games()` 会自动改读它。
REVIEW_VISIBLE_AFTER_GAMES = 3

#: 评价文字的安全上限（不是产品意义上的字数限制，只是不让单账号往库里灌大文本）。
REVIEW_TEXT_MAX_LENGTH = 5000

#: 「评价窗口即将关闭」提前量。
WINDOW_CLOSING_LEAD = timedelta(hours=24)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.get_fixed_timezone(0))


# --------------------------------------------------------------------------
# 业务异常
# --------------------------------------------------------------------------


class LikeFeatureDisabled(Forbidden):
    default_code = "like_feature_disabled"
    default_detail = "站主已关闭点赞功能，暂不能提交评价。"


class GameNotFinished(ApiError):
    # 400：团还没结团属「目标状态不对」，与 games 的 `invalid_game_status` 同档

    default_code = "review_not_open"
    default_detail = "团尚未结团，结团后方可评价。"


class ReviewWindowClosed(ApiError):
    # 400：时间窗关闭与 games 的 `card_deadline_passed`、gallery 的
    # `gallery_window_closed` 同档，都是「目标状态不对」而不是「你没权限」。
    default_code = "review_window_closed"
    default_detail = "评价时间已经过了，不能再改。"


class NotAttendee(Forbidden):
    default_code = "not_attendee"
    default_detail = "只有当场到场成员才能评价。"


class CannotReviewSelf(Forbidden):
    default_code = "cannot_review_self"
    default_detail = "不能评价自己。"


class InvalidReviewTarget(Forbidden):
    default_code = "invalid_review_target"
    default_detail = "对方当场未到场，无法评价。"


class MutualReviewDisabled(Forbidden):
    default_code = "mutual_review_disabled"
    default_detail = "本团未开启评价互见，无法查看他人给你的评价。"


# --------------------------------------------------------------------------
# 站点配置读取
# --------------------------------------------------------------------------


def like_enabled() -> bool:
    """赞功能总开关（关闭时评价入口 403、列表隐藏，数据不删）。"""
    return bool(get_config().like_feature_enabled)


def require_like_enabled() -> None:
    if not like_enabled():
        raise LikeFeatureDisabled()


def review_window() -> timedelta:
    return timedelta(days=get_config().review_window_days)


def visible_after_games() -> int:
    """延迟可见的团数：siteconfig 有该字段就读它，没有就用常量 3。"""
    return int(getattr(get_config(), "review_visible_after_games", REVIEW_VISIBLE_AFTER_GAMES))


# --------------------------------------------------------------------------
# 团与到场成员
# --------------------------------------------------------------------------


def window_ends_at(game: Game):
    """该团的评价截止时刻；团没结团时返回 None。"""
    if game.status != GAME_FINISHED or game.finished_at is None:
        return None
    return game.finished_at + review_window()


def in_review_window(game: Game, *, now=None) -> bool:
    ends_at = window_ends_at(game)
    if ends_at is None:
        return False
    return (now or timezone.now()) <= ends_at


def require_open_window(game: Game) -> None:
    if game.status != GAME_FINISHED or game.finished_at is None:
        raise GameNotFinished()
    if not in_review_window(game):
        raise ReviewWindowClosed()


def attended_signups(game: Game):
    """该团实际到场的 PL 报名行（只有 accepted + attended 算数）。"""
    return game.signups.filter(status=SIGNUP_ACCEPTED, attended=True).select_related("player")


def attendees(game: Game) -> list[tuple[object, str]]:
    """该团的到场成员 [(user, role)]：GM 永远算到场，PL 看 `attended`。"""
    members: list[tuple[object, str]] = [(game.gm, ROLE_GM)]
    members.extend((signup.player, ROLE_PL) for signup in attended_signups(game))
    return members


def role_of(user, game: Game) -> str | None:
    """`user` 在该团里的身份；不是到场成员时返回 None。"""
    if user is None or not getattr(user, "pk", None):
        return None
    if game.gm_id == user.pk:
        return ROLE_GM
    exists = game.signups.filter(player=user, status=SIGNUP_ACCEPTED, attended=True).exists()
    return ROLE_PL if exists else None


def is_attendee(user, game: Game) -> bool:
    return role_of(user, game) is not None


def reviewable_targets(user, game: Game) -> list[tuple[object, str]]:
    """`user` 在该团里可以评价的对象。

    PL 评 GM 与其他到场 PL；GM 评所有到场 PL；谁都不能评自己。
    """
    if not is_attendee(user, game):
        return []
    return [(member, role) for member, role in attendees(game) if member.pk != user.pk]


def attended_games(user):
    """`user` 实际参与（作为 GM 或到场 PL）且已结团的团。"""
    return (
        Game.objects.filter(status=GAME_FINISHED)
        .filter(
            Q(gm=user)
            | Q(signups__player=user, signups__attended=True, signups__status=SIGNUP_ACCEPTED)
        )
        .distinct()
    )


def finished_games_after(user, moment) -> int:
    """`moment` 之后又结团、且 `user` 实际参与的团数（作为 PL 或 GM 都计）。

    **只认「除自己外至少还有一位到场成员」的团**（W3 红队复现）：GM 可以凭空开一个
    零人团、`start` 完立刻 `finish`，连做三次就把延迟锁当场刷没 —— 3 人团里提前读到
    评价等于直接点名评价人。作为 PL 到场的团天然满足（至少还有 GM）；作为 GM 结的团
    要求至少有一位到场 PL。
    """
    if moment is None:
        return 0
    candidate_ids = set(
        Signup.objects.filter(
            player=user,
            attended=True,
            status=SIGNUP_ACCEPTED,
            game__status=GAME_FINISHED,
            game__finished_at__gt=moment,
        ).values_list("game_id", flat=True)
    )
    candidate_ids |= set(
        Game.objects.filter(
            gm=user, status=GAME_FINISHED, finished_at__gt=moment
        ).values_list("id", flat=True)
    )
    if not candidate_ids:
        return 0
    # 单独查一次到场 PL 数：和 `quota_for` 同一个坑，不能在带 signups 过滤的
    # queryset 上直接 annotate(Count("signups"))，那会复用被过滤的 join。
    other_attendees = dict(
        Signup.objects.filter(game_id__in=candidate_ids, attended=True, status=SIGNUP_ACCEPTED)
        .exclude(player=user)
        .values("game_id")
        .annotate(n=Count("id"))
        .values_list("game_id", "n")
    )
    gm_ids = dict(Game.objects.filter(id__in=candidate_ids).values_list("id", "gm_id"))
    return sum(
        1
        for game_id in candidate_ids
        if other_attendees.get(game_id, 0) > 0 or gm_ids.get(game_id) not in (None, user.pk)
    )


def is_visible_to_reviewee(user, game: Game) -> bool:
    """延迟可见判定：该团结团后又有 N 个团结团，该团的评价才对被评者可见。

    始终不足 N 个团则一直不可见。
    时间用严格大于，和该团结团时刻**同一瞬间**结的团不算「之后」。
    """
    if game.finished_at is None:
        return False
    return finished_games_after(user, game.finished_at) >= visible_after_games()


# --------------------------------------------------------------------------
# 匿名顺序
# --------------------------------------------------------------------------


def anonymous_sort_key(review_pk: int) -> str:
    """与创建顺序无关、稳定、且外部不可反推的排序键。

    用 `HMAC(SECRET_KEY, pk)`：
    - 稳定 —— 同一条评价每次请求排在同一位置，不会因为刷新而抖动；
    - 与创建顺序无关 —— 摘要值和 pk 的大小关系没有相关性；
    - 不可反推 —— 外部拿不到 SECRET_KEY，也拿不到 pk（接口根本不回传 id）。
    """
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"review:{review_pk}".encode(),
        hashlib.sha256,
    ).hexdigest()


def anonymize_order(reviews) -> list[Review]:
    """按「团分组 + 组内伪随机」输出。

    团本身对被评者不是秘密（响应里就带着团名与日期），所以按团的结团时间倒序分组；
    组内顺序走 `anonymous_sort_key`，**绝不按 id / created_at**。
    """

    def sort_key(review: Review):
        finished_at = review.game.finished_at or _EPOCH
        return (-finished_at.timestamp(), anonymous_sort_key(review.pk))

    return sorted(reviews, key=sort_key)


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------


@transaction.atomic
def upsert_review(reviewer, *, game: Game, reviewee, verdict: str, text: str) -> tuple[Review, bool]:
    """创建或更新一条评价（窗口内可改档与文字，不可撤回）。

    「每团每对象一次」由 `(game, reviewer, reviewee)` 唯一约束天然保证，
    所以这里是 upsert 而不是 create。
    """
    require_like_enabled()
    require_open_window(game)

    if not is_attendee(reviewer, game):
        raise NotAttendee()
    if reviewee.pk == reviewer.pk:
        raise CannotReviewSelf()

    target_role = role_of(reviewee, game)
    if target_role is None:
        raise InvalidReviewTarget()

    review, created = Review.objects.update_or_create(
        game=game,
        reviewer=reviewer,
        reviewee=reviewee,
        defaults={"verdict": verdict, "text": text, "reviewee_role": target_role},
    )
    refresh_reviewee_stats(reviewee, target_role)
    return review, created


def refresh_reviewee_stats(user, role: str) -> None:
    """评价落库后刷新被评者对应那一侧的卡（GM 评价进 GM 卡，PL 评价进玩家卡）。"""
    from apps.profiles.services import recompute_gm_card, recompute_player_card

    if role == ROLE_GM:
        recompute_gm_card(user)
    else:
        recompute_player_card(user)


# --------------------------------------------------------------------------
# 统计 provider（在 apps.py 的 ready() 里注册到 profiles）
# --------------------------------------------------------------------------


def window_closed(game: Game, *, now=None) -> bool:
    """该团已结团且评价窗口已经关闭（窗口内没提交的仍是「待评价」，不是「无评价」）。"""
    ends_at = window_ends_at(game)
    return ends_at is not None and (now or timezone.now()) > ends_at


def expected_reviewer_ids(user, game: Game) -> set[int]:
    """应评价 `user` 的人：镜像 `reviewable_targets` —— 到场成员互评、不评自己。

    `user` 本人不是到场成员时返回空集（他不是这个团的被评对象）。
    """
    if not is_attendee(user, game):
        return set()
    return {member.pk for member, _role in attendees(game) if member.pk != user.pk}


def review_counts(user, role: str, *, now=None) -> dict:
    """某人某一侧的评价统计：`reviews_received` = 赞 + 倒赞 + 无评价。"""
    now = now or timezone.now()
    rows = Review.objects.filter(reviewee=user, reviewee_role=role).select_related("game")
    # 延迟是按「团」判定的，按 game 缓存一次，别对每条评价各查一遍。
    visible_by_game: dict[int, bool] = {}
    counts = {"reviews_received": 0, "likes": 0, "dislikes": 0}
    for review in rows:
        visible = visible_by_game.get(review.game_id)
        if visible is None:
            visible = is_visible_to_reviewee(user, review.game)
            visible_by_game[review.game_id] = visible
        if not visible:
            continue
        counts["reviews_received"] += 1
        if review.verdict == VERDICT_LIKE:
            counts["likes"] += 1
        elif review.verdict == VERDICT_DISLIKE:
            counts["dislikes"] += 1

    closed_games = attended_games(user).filter(finished_at__lt=now - review_window())
    for game in closed_games:
        if not window_closed(game, now=now) or role_of(user, game) != role:
            continue
        visible = visible_by_game.get(game.pk)
        if visible is None:
            visible = is_visible_to_reviewee(user, game)
        if not visible:
            continue
        reviewed = set(
            Review.objects.filter(game=game, reviewee=user, reviewee_role=role).values_list(
                "reviewer_id", flat=True
            )
        )
        counts["reviews_received"] += len(expected_reviewer_ids(user, game) - reviewed)
    return counts


def player_review_stats_provider(user) -> dict:
    return review_counts(user, ROLE_PL)


def gm_review_stats_provider(user) -> dict:
    return review_counts(user, ROLE_GM)


# --------------------------------------------------------------------------
# 读取：待评 / 本人发出 / 本人收到 / 互见 / 配额
# --------------------------------------------------------------------------


def pending_for(user) -> list[dict]:
    """本人待评对象：已结团、在窗口内、还没评过的人。"""
    require_like_enabled()
    now = timezone.now()
    result: list[dict] = []
    games = attended_games(user).select_related("gm").order_by("-finished_at")
    for game in games:
        if not in_review_window(game, now=now):
            continue
        reviewed = set(
            Review.objects.filter(game=game, reviewer=user).values_list("reviewee_id", flat=True)
        )
        targets = [
            {"user": member, "role": role}
            for member, role in reviewable_targets(user, game)
            if member.pk not in reviewed
        ]
        if targets:
            result.append({"game": game, "window_ends_at": window_ends_at(game), "targets": targets})
    return result


def given_by(user) -> list[Review]:
    """本人发出的评价（本人当然知道自己评了谁，这里可以带 reviewee）。"""
    if not like_enabled():
        return []
    return list(
        Review.objects.filter(reviewer=user)
        .select_related("game", "reviewee")
        .order_by("-created_at", "-id")
    )


def received_by(user) -> tuple[list[Review], int]:
    """本人收到的评价：过了延迟的按匿名顺序返回，没过的只给一个「尚不可见」计数。

    返回 `(可见列表, 尚不可见条数)`。**这里绝不 order_by**，顺序由
    `anonymize_order` 在内存里决定（见模块头「顺序锁」）。
    """
    if not like_enabled():
        return [], 0
    visible: list[Review] = []
    hidden = 0
    for review in Review.objects.filter(reviewee=user).select_related("game"):
        if is_visible_to_reviewee(user, review.game):
            visible.append(review)
        else:
            hidden += 1
    return anonymize_order(visible), hidden


def mutual_for(user, game: Game) -> dict:
    """评价互见：开团时勾选后，同团到场成员可看到彼此**收到**的评价。

    - 同样匿名（不带评价人）、同样按匿名顺序输出；
    - 延迟规则按**查看者**判定：查看者对该团的延迟没过，整个互见面板就不开，
      否则查看者能靠互见面板提前读到自己收到的评价，绕过时间锁。
    """
    require_like_enabled()
    if game.status != GAME_FINISHED or game.finished_at is None:
        raise GameNotFinished()
    if not game.mutual_review:
        raise MutualReviewDisabled()
    if not is_attendee(user, game):
        raise NotAttendee()

    if not is_visible_to_reviewee(user, game):
        return {"game": game, "available": False, "groups": []}

    rows = Review.objects.filter(game=game).select_related("game")
    by_reviewee: dict[int, list[Review]] = {}
    for review in rows:
        by_reviewee.setdefault(review.reviewee_id, []).append(review)

    groups = [
        {
            "user": member,
            "role": role,
            "reviews": anonymize_order(by_reviewee.get(member.pk, [])),
        }
        for member, role in attendees(game)
    ]
    return {"game": game, "available": True, "groups": groups}


def quota_for(user) -> dict:
    """业务规则与安全约束。"""
    game_ids = list(attended_games(user).values_list("id", flat=True))
    # 单独查一次到场人数：`attended_games` 里已经为了筛人 join 过 signups，
    # 在同一个 queryset 上 annotate(Count("signups")) 会复用那个被过滤的 join，数出来是错的。
    attended_players = dict(
        Signup.objects.filter(game_id__in=game_ids, attended=True, status=SIGNUP_ACCEPTED)
        .values("game_id")
        .annotate(n=Count("id"))
        .values_list("game_id", "n")
    )
    # 团人数 = 到场 PL + GM(1)；配额扣掉自己一个，所以恰好等于到场 PL 数。
    total = sum(attended_players.get(game_id, 0) + 1 - 1 for game_id in game_ids)
    used = Review.objects.filter(reviewer=user).count()
    return {
        "quota": total,
        "used": used,
        "remaining": max(total - used, 0),
        "like_feature_enabled": like_enabled(),
    }


# --------------------------------------------------------------------------
# 定时任务：评价窗口即将关闭
# --------------------------------------------------------------------------


def run_window_closing_cycle(*, now=None) -> dict:
    """给窗口只剩 `WINDOW_CLOSING_LEAD` 的团发「评价窗口即将关闭」提醒，每团一次。

    只提醒**还有人没评**的成员；通知里只有团名与截止时间，不含任何评价人线索。
    """
    from apps.notifications import events
    from apps.notifications.services import notify
    from apps.reviews.models import ReviewWindowNotice

    if not like_enabled():
        return {"games": 0, "notified": 0}

    now = now or timezone.now()
    window = review_window()
    games = (
        Game.objects.filter(status=GAME_FINISHED, finished_at__isnull=False)
        .filter(finished_at__lte=now - (window - WINDOW_CLOSING_LEAD), finished_at__gt=now - window)
        .filter(review_window_notice__isnull=True)
        .select_related("gm")
    )

    touched = 0
    notified = 0
    for game in games:
        ends_at = window_ends_at(game)
        for member, _role in attendees(game):
            reviewed = set(
                Review.objects.filter(game=game, reviewer=member).values_list(
                    "reviewee_id", flat=True
                )
            )
            remaining = [
                target for target, _r in reviewable_targets(member, game) if target.pk not in reviewed
            ]
            if not remaining:
                continue
            notify(
                member,
                events.REVIEW_WINDOW_CLOSING,
                target=game,
                payload={
                    "game_title": game.title,
                    "ends_at": ends_at.isoformat() if ends_at else None,
                    "pending": len(remaining),
                },
            )
            notified += 1
        ReviewWindowNotice.objects.get_or_create(game=game)
        touched += 1
    return {"games": touched, "notified": notified}


# --------------------------------------------------------------------------
# 定时任务：评价窗口关闭后重算卡片（「无评价」在这一刻才计入）
# --------------------------------------------------------------------------


def run_window_closed_cycle(*, now=None) -> dict:
    """窗口已关闭、还没处理过的团：重算全体到场成员对应那一侧的卡，每团一次。

    「无评价」只在窗口关闭后计入（`review_counts`），而窗口关闭不伴随任何写操作，
    缓存的被评次数 / 赞级别不会自己变 —— 所以由每小时的定时任务补一次重算。
    靠 `ReviewWindowClosure` 去重，漏跑几小时也会在下一轮补上。
    赞功能关闭时照样重算（计数照常维护，档位由 `level_for` 统一压成空）。
    """
    from apps.reviews.models import ReviewWindowClosure

    now = now or timezone.now()
    games = (
        Game.objects.filter(status=GAME_FINISHED, finished_at__isnull=False)
        .filter(finished_at__lt=now - review_window())
        .filter(review_window_closure__isnull=True)
        .select_related("gm")
    )
    touched = 0
    refreshed = 0
    for game in games:
        if not window_closed(game, now=now):
            continue
        for member, role in attendees(game):
            refresh_reviewee_stats(member, role)
            refreshed += 1
        ReviewWindowClosure.objects.get_or_create(game=game)
        touched += 1
    return {"games": touched, "refreshed": refreshed}


def recalc_all_cards() -> dict:
    """一次性重算全部玩家卡 / GM 卡（存量数据、口径变更后用）。"""
    from apps.profiles.models import GMCard, PlayerCard
    from apps.profiles.services import recompute_gm_card, recompute_player_card

    players = 0
    for card in PlayerCard.objects.select_related("user"):
        recompute_player_card(card.user)
        players += 1
    gms = 0
    for card in GMCard.objects.select_related("user"):
        recompute_gm_card(card.user)
        gms += 1
    return {"player_cards": players, "gm_cards": gms}
