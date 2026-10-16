"""团的业务逻辑。视图只做鉴权与序列化，规则全部落在这里。"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.charactercards.models import STATUS_ALIVE as CARD_STATUS_ALIVE
from apps.games.models import (
    ACTIVE_STATUSES,
    GAME_CANCELLED,
    GAME_CLOSED_SIGNUP,
    GAME_FINISHED,
    GAME_RECRUITING,
    GAME_RUNNING,
    OCCUPYING_STATUSES,
    OPEN_STATUSES,
    SIGNUP_ACCEPTED,
    SIGNUP_FIRST_COME,
    SIGNUP_NO_CARD,
    SIGNUP_PENDING,
    SIGNUP_REJECTED,
    SIGNUP_REMOVED,
    SIGNUP_SUBMITTED,
    SIGNUP_WITHDRAWN,
    Game,
    Session,
    Signup,
    Tag,
)
from apps.notifications import events
from apps.notifications.services import notify
from apps.profiles import levels
from apps.siteconfig.services import get_config

# AccountMuted 只是转出来给 `services.AccountMuted` 这个老写法用，本模块不直接引用它。
from common.exceptions import (  # noqa: F401
    AccountMuted,
    ApiError,
    Forbidden,
)

# 提醒提前量：交卡截止前 24 小时、开团前 24 小时
REMINDER_LEAD = timedelta(hours=24)


# --------------------------------------------------------------------------
# 业务异常
# --------------------------------------------------------------------------


class NotGM(Forbidden):
    default_code = "not_gm"
    default_detail = "只有 GM 才能放团。"


class NotGameGM(Forbidden):
    default_code = "not_game_gm"
    default_detail = "只有本团的 GM 才能做这件事。"


# 禁言 / 封禁 / 注销的异常统一在 `common.exceptions`（缺陷 D4）：
# 权限类（IsNotMuted）与 service 层（_assert_can_act）必须抛同一个 code，
# 否则同一件事从两条路径进来会给前端两种答案。


class InvalidPlayerRange(ApiError):
    default_code = "invalid_player_range"
    default_detail = "人数范围填写有误。"


class CardDeadlineAfterStart(ApiError):
    default_code = "card_deadline_after_start"
    default_detail = "交卡截止不得晚于开团时间。"


class GameNotRecruiting(ApiError):
    default_code = "game_not_recruiting"
    default_detail = "本团目前不接受报名。"


class GameFull(ApiError):
    default_code = "game_full"
    default_detail = "本团报名人数已满。"


class AlreadySignedUp(ApiError):
    default_code = "already_signed_up"
    default_detail = "你已经报名过本团。"


class SignupClosedForYou(Forbidden):
    default_code = "signup_closed_for_you"
    default_detail = "GM 已处理过你的这次报名，无法再次报名。"


class CannotSignupOwnGame(Forbidden):
    default_code = "cannot_signup_own_game"
    default_detail = "不能报名自己开的团。"


class ThresholdNotMet(Forbidden):
    default_code = "threshold_not_met"
    default_detail = "你还不满足本团的报名条件。"


class NotPrevMember(Forbidden):
    default_code = "not_prev_member"
    default_detail = "本团仅限上一场到场成员报名。"


class CardNotRequired(ApiError):
    default_code = "card_not_required"
    default_detail = "本团无需交卡。"


class CardDeadlinePassed(ApiError):
    default_code = "card_deadline_passed"
    default_detail = "交卡时间已截止。"


class CardNotUsable(ApiError):
    default_code = "card_not_usable"
    default_detail = "这张卡已撕毁，无法用于报名。"


class SignupCardFileMissing(ApiError):
    """400：卡本身还在，但一个文件版本都没有（缺陷 D3）。

    和 charactercards 下载口的 `card_file_missing` 是同一件事的两头：那边是
    「文件不存在」→ 404，这边是「这次请求交的卡是空的」→ 400（状态码矩阵第 3 格：
    目标状态不对）。** 拆码**：两头原本共用一个 code，可该说的话不一样
    （那边「这张卡还没有文件。」，这边要指路「先上传文件后再交卡」），
    前端按 code 映射必然覆盖错一边，所以这一头改名 `signup_card_file_missing`。
    文案一字未改。
    """

    default_code = "signup_card_file_missing"
    default_detail = "这张卡尚未上传文件，请先上传文件后再交卡。"


class InvalidGameStatus(ApiError):
    default_code = "invalid_game_status"
    default_detail = "本团目前不支持此项变更。"


class InvalidSignupStatus(ApiError):
    default_code = "invalid_signup_status"
    default_detail = "这份报名目前不支持此项变更。"


class NoAttendee(ApiError):
    default_code = "no_attendee"
    default_detail = "结团前须至少勾选一位到场成员。"


class MutualReviewFrozen(ApiError):
    default_code = "mutual_review_frozen"
    default_detail = "已有人报名，评价互见设置不能再修改。"


class ReasonRequired(ApiError):
    default_code = "reason_required"
    default_detail = "请填写理由。"


class SessionIndexTaken(ApiError):
    default_code = "session_index_taken"
    default_detail = "这个场次序号已被使用。"


# --------------------------------------------------------------------------
# 门槛
# --------------------------------------------------------------------------


def effective_thresholds(game: Game) -> tuple[int | None, str]:
    """返回当前**生效**的门槛。

    站主关闭赞功能时「门槛字段同时失效，已设门槛的团视为无门槛」。
    这里按字面实现为**两个门槛都失效**（含最低团次数）——属实现解读，
    若只想让赞级别门槛失效，改本函数一处即可。
    """
    if not get_config().like_feature_enabled:
        return None, ""
    return game.min_play_count, game.min_level


def level_meets(player_level: str, required_level: str) -> bool:
    """玩家档位是否够得上要求的档位。空的 `player_level` = 无档位，一律不够。"""
    if not required_level:
        return True
    if not player_level:
        return False
    order = levels.LEVEL_ORDER
    try:
        return order.index(player_level) <= order.index(required_level)
    except ValueError:  # pragma: no cover - 脏数据兜底
        return False


def check_thresholds(user, game: Game) -> None:
    """门槛校验：读玩家卡的缓存字段（团次数、档位），不现算。"""
    from apps.profiles.services import ensure_player_card

    min_play_count, min_level = effective_thresholds(game)
    if min_play_count is None and not min_level:
        return

    card = ensure_player_card(user)
    if min_play_count is not None and card.games_played < min_play_count:
        raise ThresholdNotMet(f"本团要求至少有 {min_play_count} 次参团经历。")
    if min_level and not level_meets(card.level, min_level):
        if not card.level:
            raise ThresholdNotMet("本团按点赞档位招募，你还没有公开点赞档位。")
        raise ThresholdNotMet(
            f"本团要求点赞档位不低于「{levels.LEVEL_LABELS.get(min_level, min_level)}」。"
        )


# --------------------------------------------------------------------------
# 可见性
# --------------------------------------------------------------------------


def is_game_gm(user, game: Game) -> bool:
    return bool(
        user is not None and getattr(user, "is_authenticated", False) and game.gm_id == user.pk
    )


def is_team_member(user, game: Game) -> bool:
    """同团 = GM 本人，或本团 accepted 的报名者（正式名单的可见范围）。"""
    if not getattr(user, "is_authenticated", False):
        return False
    if game.gm_id == user.pk:
        return True
    return Signup.objects.filter(game=game, player=user, status=SIGNUP_ACCEPTED).exists()


def recruiting_roster(game: Game) -> QuerySet[Signup]:
    """招募中名单：未定下来的报名（待交卡 / 已交卡待审），登录用户可见，含报名顺序。"""
    return (
        game.signups.filter(status__in=(SIGNUP_PENDING, SIGNUP_SUBMITTED))
        .select_related("player")
        .order_by("order", "id")
    )


def accepted_roster(game: Game) -> QuerySet[Signup]:
    """正式名单：审卡通过的人，只对同团（GM + accepted）可见。"""
    return (
        game.signups.filter(status=SIGNUP_ACCEPTED)
        .select_related("player", "card")
        .order_by("order", "id")
    )


def gm_roster(game: Game) -> QuerySet[Signup]:
    """GM 面板名单：所有报名（含被拒/退出/未交卡），带卡信息。"""
    return game.signups.select_related("player", "card").order_by("order", "id")


# --------------------------------------------------------------------------
# 放团 / 改团
# --------------------------------------------------------------------------


def _assert_can_act(user) -> None:
    if getattr(user, "is_muted", False):
        raise AccountMuted()


def _validate_range(min_players: int, max_players: int) -> None:
    if min_players < 1:
        raise InvalidPlayerRange("最少人数至少为 1。")
    if max_players < min_players:
        raise InvalidPlayerRange("最多人数不能小于最少人数。")


def _validate_deadline(start_at, card_deadline) -> None:
    if card_deadline > start_at:
        raise CardDeadlineAfterStart()


def _field_or_default(fields: dict, name: str) -> int:
    """取字段值；只有「没给」才回落到模型默认值，0 / 负数要原样送去校验。"""
    value = fields.get(name)
    if value is None:
        value = Game._meta.get_field(name).default
    return int(value)


@transaction.atomic
def create_game(gm, *, tags: list[str] | None = None, **fields) -> Game:
    """放团。只有 GM 且未禁言能放；战役后续团的人数范围默认沿用前团。"""
    if not getattr(gm, "is_gm", False):
        raise NotGM()
    _assert_can_act(gm)

    prev: Game | None = fields.get("campaign_prev")
    if prev is not None:

        fields.setdefault("min_players", prev.min_players)
        fields.setdefault("max_players", prev.max_players)
        if fields.get("min_players") is None:
            fields["min_players"] = prev.min_players
        if fields.get("max_players") is None:
            fields["max_players"] = prev.max_players

    start_at = fields["start_at"]
    if not fields.get("card_deadline"):
        fields["card_deadline"] = start_at
    # 注意不能写 `fields.get("min_players") or 默认值`：min_players=0 是假值，
    # 会被悄悄换成 1 通过校验，然后以 0 落库（W2 红队复现）。
    _validate_range(
        _field_or_default(fields, "min_players"), _field_or_default(fields, "max_players")
    )
    _validate_deadline(start_at, fields["card_deadline"])

    game = Game.objects.create(gm=gm, **fields)
    if tags:
        game.tags.set(resolve_tags(tags))
    return game


@transaction.atomic
def update_game(game: Game, *, tags: list[str] | None = None, **fields) -> Game:
    """改团公告。截止时间仍不得晚于开团时间。"""
    if game.is_over:
        raise InvalidGameStatus("已结团或已取消的团不能再修改。")
    _assert_mutual_review_mutable(game, fields)

    for key, value in fields.items():
        setattr(game, key, value)
    if game.card_deadline is None:
        # 序列化器允许传 null（= 清空），口径与放团一致：回落到开团时间。
        # 不兜住的话 `_validate_deadline` 会拿 None 比大小，直接 500（W2 红队复现）。
        game.card_deadline = game.start_at
    _validate_range(game.min_players, game.max_players)
    _validate_deadline(game.start_at, game.card_deadline)
    game.save()

    if tags is not None:
        game.tags.set(resolve_tags(tags))
    sync_capacity_status(game)
    return game


def _assert_mutual_review_mutable(game: Game, fields: dict) -> None:
    """评价互见开关**在出现第一条报名之后就冻结**（W5，红队 W3 建议）。

    成员是在报名那一刻按当时的开关值同意的：报名时写着「不互见」，跑完团 GM
    再把它翻开，等于把每个人收到的评价在同团内公开，而没人同意过这件事。
    原来只有「已结团/已取消」才拦得住（`is_over`），缺的正是「招募中→跑完但还没结团」
    这一整段（reviews 红队 `test_跑完还没结团时不应再翻开互见开关` 复现）。
    """
    if "mutual_review" not in fields:
        return
    if bool(fields["mutual_review"]) == bool(game.mutual_review):
        return  # 值没变，不算改动
    if game.signups.exists():
        raise MutualReviewFrozen()


def resolve_tags(names: list[str]) -> list[Tag]:
    """标签按名字复用，没有就建（预设标签由数据迁移创建，不会被这里改成非预设）。"""
    tags = []
    for raw in names:
        name = (raw or "").strip()
        if not name:
            continue
        tag, _ = Tag.objects.get_or_create(name=name)
        if tag not in tags:
            tags.append(tag)
    return tags


def sync_capacity_status(game: Game) -> Game:
    """满员即关闭报名；空出位置（或 GM 扩容）后自动重新开放。"""
    if game.status not in OPEN_STATUSES:
        return game
    target = GAME_CLOSED_SIGNUP if game.is_full else GAME_RECRUITING
    if game.status != target:
        game.status = target
        game.save(update_fields=["status", "updated_at"])
    return game


def expand_capacity(game: Game, *, max_players: int) -> Game:
    """GM 扩容：不做候补队列，满员后靠 GM 手动扩容重新开放。"""
    if game.is_over:
        raise InvalidGameStatus("已结团或已取消的团不能扩容。")
    if max_players < game.min_players:
        raise InvalidPlayerRange("最多人数不能小于最少人数。")
    game.max_players = max_players
    game.save(update_fields=["max_players", "updated_at"])
    return sync_capacity_status(game)


# --------------------------------------------------------------------------
# 报名
# --------------------------------------------------------------------------


@transaction.atomic
def signup(game: Game, player) -> Signup:
    """报名：登录、未禁言、不是 GM 本人、招募中、未满员、过门槛、（战役）是前团到场成员。"""
    _assert_can_act(player)
    game = Game.objects.select_for_update().get(pk=game.pk)

    if game.gm_id == player.pk:
        raise CannotSignupOwnGame()
    refresh_game(game)
    if game.status not in OPEN_STATUSES:
        raise GameNotRecruiting()
    if game.is_full:
        # 满员的团状态是 closed_signup，这里要回「满员」而不是笼统的「不接受报名」。
        raise GameFull()
    if game.status != GAME_RECRUITING:
        raise GameNotRecruiting()

    existing = Signup.objects.filter(game=game, player=player).first()
    if existing is not None:
        if existing.status in OCCUPYING_STATUSES or existing.status == SIGNUP_NO_CARD:
            raise AlreadySignedUp()
        if existing.status in (SIGNUP_REJECTED, SIGNUP_REMOVED):
            # 被 GM 拒/移出的人不能自己再报回来，避免绕过 GM 的处置。
            raise SignupClosedForYou()

    check_thresholds(player, game)

    if game.restrict_to_prev_members:
        prev = game.campaign_prev
        if prev is None:
            raise NotPrevMember("本团已设置「仅限上一场到场成员」，但未指定具体场次，请联系 GM 修改。")
        if not Signup.objects.filter(
            game=prev, player=player, status=SIGNUP_ACCEPTED, attended=True
        ).exists():
            raise NotPrevMember()

    # 免交卡团：先到先得直接成功报团；PL 池模式仍要 GM 审（「报名通过即成功报团」）。
    if not game.requires_card:
        status = SIGNUP_ACCEPTED if game.signup_mode == SIGNUP_FIRST_COME else SIGNUP_SUBMITTED
    else:
        status = SIGNUP_PENDING

    if existing is not None:  # 只有 withdrawn 会走到这里：允许自己退了再报
        existing.status = status
        existing.order = _next_order(game)
        existing.card = None
        existing.card_uploaded_by_gm = False
        existing.card_submitted_at = None
        existing.withdraw_requested_at = None
        existing.withdraw_reason = ""
        existing.review_note = ""
        existing.decided_at = timezone.now() if status == SIGNUP_ACCEPTED else None
        existing.save()
        record = existing
    else:
        record = Signup.objects.create(
            game=game,
            player=player,
            order=_next_order(game),
            status=status,
            decided_at=timezone.now() if status == SIGNUP_ACCEPTED else None,
        )

    # 写入后再按实际占位数复查一次：上面的 `select_for_update` 只在支持行锁的后端
    # （PostgreSQL）生效，开发/测试用的 SQLite 会**静默忽略**它，
    # 「检查容量 → 写入」之间仍有竞态窗口。本函数是 atomic 的，这里抛异常即回滚。
    if game.occupied_seats > game.max_players:
        raise GameFull()

    sync_capacity_status(game)
    notify(
        game.gm,
        events.SIGNUP_RECEIVED,
        actor=player,
        target=game,
        payload={"game_title": game.title, "signup_id": record.pk, "order": record.order},
    )
    if status == SIGNUP_ACCEPTED:
        notify(
            player,
            events.SIGNUP_RESULT,
            target=game,
            payload={"game_title": game.title, "result": SIGNUP_ACCEPTED},
        )
    return record


def _next_order(game: Game) -> int:
    last = game.signups.order_by("-order").values_list("order", flat=True).first()
    return (last or 0) + 1


def refresh_member_cards(user) -> None:
    """重算某人两侧的缓存卡片。

    任何改动 `Signup.status` / `attended` 的动作都要调它：玩家卡的 `games_played`、
    GM 卡的 `games_hosted`、以及 reviews 注册进来的赞/倒赞/被评次数统计**全部是
    按 DB 现状重算的缓存字段**，而报名门槛（`check_thresholds`）读的就是这些缓存。
    漏掉一处就会出现「名单已经变了、卡片还停在旧值」的漂移。
    GM 卡只在对方确实是 GM 时才刷，免得给普通用户凭空建一张空 GM 卡。
    """
    from apps.profiles.services import recompute_gm_card, recompute_player_card

    recompute_player_card(user)
    if getattr(user, "is_gm", False):
        recompute_gm_card(user)


def _assert_roster_mutable(game: Game) -> None:
    """名单在结团 / 取消之后冻结。

    否则 GM 结完团还能把人审批进正式名单（拿到同团可见性与评价资格），
    或者把已计数的到场者移出（让缓存字段与 `player_games_played` 的口径对不上）
    —— W2 红队复现，测试见 `test_adversarial_state.py`。
    """
    if game.is_over:
        raise InvalidGameStatus("团已结束，名单不能再改动。")


@transaction.atomic
def withdraw(signup_obj: Signup, *, reason: str = "", now=None) -> dict:
    """PL 退出。

    截止前自由退；截止后退出需 GM 确认。
    这里的「截止」= 交卡截止（`card_deadline`，免交卡团也有，默认 = 开团时间）。
    返回 {"withdrawn": bool, "pending_gm_confirm": bool}。
    """
    now = now or timezone.now()
    game = signup_obj.game
    if game.is_over:
        raise InvalidGameStatus("团已结束，不能再退出。")
    if signup_obj.status not in ACTIVE_STATUSES:
        raise InvalidSignupStatus()

    if now <= game.card_deadline:
        signup_obj.status = SIGNUP_WITHDRAWN
        signup_obj.withdraw_reason = reason
        signup_obj.decided_at = now
        signup_obj.save(update_fields=["status", "withdraw_reason", "decided_at", "updated_at"])
        sync_capacity_status(game)
        refresh_member_cards(signup_obj.player)
        notify(
            game.gm,
            events.SIGNUP_RESULT,
            actor=signup_obj.player,
            target=game,
            payload={"game_title": game.title, "kind": "withdrawn", "reason": reason},
        )
        return {"withdrawn": True, "pending_gm_confirm": False}

    signup_obj.withdraw_requested_at = now
    signup_obj.withdraw_reason = reason
    signup_obj.save(update_fields=["withdraw_requested_at", "withdraw_reason", "updated_at"])
    notify(
        game.gm,
        events.SIGNUP_RESULT,
        actor=signup_obj.player,
        target=game,
        payload={"game_title": game.title, "kind": "withdraw_requested", "reason": reason},
    )
    return {"withdrawn": False, "pending_gm_confirm": True}


@transaction.atomic
def confirm_withdraw(signup_obj: Signup, *, approved: bool = True, note: str = "") -> Signup:
    """GM 确认（或驳回）截止后的退出申请。"""
    _assert_roster_mutable(signup_obj.game)
    if signup_obj.withdraw_requested_at is None:
        raise InvalidSignupStatus("这份报名没有待确认的退出申请。")

    if approved:
        signup_obj.status = SIGNUP_WITHDRAWN
    signup_obj.withdraw_requested_at = None
    signup_obj.review_note = note
    signup_obj.decided_at = timezone.now()
    signup_obj.save(update_fields=["status", "withdraw_requested_at", "review_note", "decided_at", "updated_at"])
    sync_capacity_status(signup_obj.game)
    refresh_member_cards(signup_obj.player)
    notify(
        signup_obj.player,
        events.SIGNUP_RESULT,
        target=signup_obj.game,
        payload={
            "game_title": signup_obj.game.title,
            "kind": "withdraw_confirmed" if approved else "withdraw_rejected",
            "note": note,
        },
    )
    return signup_obj


@transaction.atomic
def gm_remove(signup_obj: Signup, *, reason: str) -> Signup:
    """GM 移除报名者：必须写理由，PL 收通知。"""
    reason = (reason or "").strip()
    if not reason:
        raise ReasonRequired("移除报名者时须填写理由。")
    _assert_roster_mutable(signup_obj.game)
    if signup_obj.status not in ACTIVE_STATUSES:
        raise InvalidSignupStatus()

    signup_obj.status = SIGNUP_REMOVED
    signup_obj.review_note = reason
    signup_obj.decided_at = timezone.now()
    signup_obj.withdraw_requested_at = None
    signup_obj.save(update_fields=["status", "review_note", "decided_at", "withdraw_requested_at", "updated_at"])
    sync_capacity_status(signup_obj.game)
    refresh_member_cards(signup_obj.player)
    notify(
        signup_obj.player,
        events.SIGNUP_RESULT,
        target=signup_obj.game,
        payload={"game_title": signup_obj.game.title, "kind": "removed", "reason": reason},
    )
    return signup_obj


# --------------------------------------------------------------------------
# 交卡与审批
# --------------------------------------------------------------------------


def _assert_card_window(game: Game, *, now=None) -> None:
    now = now or timezone.now()
    if game.status not in OPEN_STATUSES:
        raise InvalidGameStatus("团已开始，无法再交卡。")
    if now > game.card_deadline:
        raise CardDeadlinePassed()


@transaction.atomic
def submit_card(signup_obj: Signup, card, *, now=None) -> Signup:
    """PL 交卡。

    - 先到先得：交卡即 accepted（成功报团）。
    - PL 池 + 人工审核：进 submitted，等 GM 审批。
    """
    now = now or timezone.now()
    game = signup_obj.game
    _assert_can_act(signup_obj.player)
    if not game.requires_card:
        raise CardNotRequired()
    _assert_card_window(game, now=now)
    if signup_obj.status not in (SIGNUP_PENDING, SIGNUP_SUBMITTED, SIGNUP_ACCEPTED):
        raise InvalidSignupStatus()
    if card.owner_id != signup_obj.player_id:
        raise CardNotUsable("只能交自己的角色卡。")
    # 两个不可用原因分开报，前端才能给出不同的下一步（去建卡 / 去传文件）。
    if card.status != CARD_STATUS_ALIVE:
        raise CardNotUsable()
    if not card.has_file:
        raise SignupCardFileMissing()

    signup_obj.card = card
    signup_obj.card_uploaded_by_gm = False
    signup_obj.card_submitted_at = now
    if game.signup_mode == SIGNUP_FIRST_COME:
        signup_obj.status = SIGNUP_ACCEPTED
        signup_obj.decided_at = now
    else:
        signup_obj.status = SIGNUP_SUBMITTED
    signup_obj.save()

    sync_capacity_status(game)
    notify(
        game.gm,
        events.CARD_SUBMITTED,
        actor=signup_obj.player,
        target=game,
        payload={"game_title": game.title, "signup_id": signup_obj.pk, "card_name": card.name},
    )
    if signup_obj.status == SIGNUP_ACCEPTED:
        notify(
            signup_obj.player,
            events.CARD_REVIEW_RESULT,
            target=game,
            payload={"game_title": game.title, "result": SIGNUP_ACCEPTED, "auto": True},
        )
    return signup_obj


@transaction.atomic
def gm_upload_card(
    signup_obj: Signup,
    uploaded_file,
    *,
    gm,
    name: str = "",
    rule_system: str = "",
    note: str = "",
) -> Signup:
    """GM 代 PL 上传卡并直接通过。

    卡的建与存全部走 charactercards 的 services，本 app 不碰文件。
    """
    from apps.charactercards import services as card_services

    game = signup_obj.game
    if game.is_over:
        raise InvalidGameStatus("团已结束，不能再代传卡")
    if signup_obj.status not in ACTIVE_STATUSES:
        raise InvalidSignupStatus()

    card = card_services.create_card(
        signup_obj.player,
        name=(name or f"{signup_obj.player.nickname} 的角色卡").strip(),
        rule_system=(rule_system or game.rule_system or "").strip(),
        is_public=False,
        note=note,
    )
    card_services.add_file_version(card, uploaded_file, uploaded_by=gm, uploaded_by_gm=True)
    # 后置校验（缺陷 D3）：代传这条路也不许留下空壳卡。
    # 正常情况下上一行要么落盘要么抛校验错，这里兜的是「将来有人把 add_file_version
    # 改成可跳过」的情形 —— 名单上挂着一张点不开的卡比直接报错更难查。
    if not card.has_file:
        raise SignupCardFileMissing("文件保存失败，请重新上传。")

    now = timezone.now()
    signup_obj.card = card
    signup_obj.card_uploaded_by_gm = True
    signup_obj.card_submitted_at = now
    signup_obj.status = SIGNUP_ACCEPTED
    signup_obj.decided_at = now
    signup_obj.save()

    sync_capacity_status(game)
    notify(
        signup_obj.player,
        events.CARD_REVIEW_RESULT,
        actor=gm,
        target=game,
        payload={"game_title": game.title, "result": SIGNUP_ACCEPTED, "uploaded_by_gm": True},
    )
    return signup_obj


@transaction.atomic
def review_signup(signup_obj: Signup, *, approved: bool, note: str = "") -> Signup:
    """GM 审批（PL 池模式的交卡审核，也用于处置未交卡者）。"""
    _assert_roster_mutable(signup_obj.game)
    if signup_obj.status not in ACTIVE_STATUSES:
        raise InvalidSignupStatus()
    if approved and signup_obj.game.is_full and signup_obj.status not in OCCUPYING_STATUSES:
        raise GameFull()

    signup_obj.status = SIGNUP_ACCEPTED if approved else SIGNUP_REJECTED
    signup_obj.review_note = note
    signup_obj.decided_at = timezone.now()
    signup_obj.save(update_fields=["status", "review_note", "decided_at", "updated_at"])

    sync_capacity_status(signup_obj.game)
    refresh_member_cards(signup_obj.player)
    notify(
        signup_obj.player,
        events.CARD_REVIEW_RESULT,
        target=signup_obj.game,
        payload={
            "game_title": signup_obj.game.title,
            "result": signup_obj.status,
            "note": note,
        },
    )
    return signup_obj


def mark_no_card_signups(game: Game, *, now=None) -> int:
    """截止后仍未交卡的报名标成 `no_card`，交给 GM 处置（接受或移除）。

    惰性调用（读团时）与定时任务都会走这里；状态只会翻一次，所以通知不会重复。
    """
    now = now or timezone.now()
    if now <= game.card_deadline or not game.requires_card or game.is_over:
        return 0

    stale = list(game.signups.filter(status=SIGNUP_PENDING).select_related("player"))
    for record in stale:
        record.status = SIGNUP_NO_CARD
        record.save(update_fields=["status", "updated_at"])
        notify(
            record.player,
            events.CARD_REVIEW_RESULT,
            target=game,
            payload={"game_title": game.title, "result": SIGNUP_NO_CARD},
        )
    if stale:
        # 未交卡的人不再占位，空出来的位置要和「退出/被移除」一样重新开放
        # （architecture 16.2），否则满员的团会永远卡在 closed_signup。
        # 先把 status 读回来：调用方手里的实例可能是满员之前取的，
        # 拿着过期的 status 去比对会让 `sync_capacity_status` 误判成「不用改」。
        game.refresh_from_db(fields=["status"])
        sync_capacity_status(game)
    return len(stale)


# --------------------------------------------------------------------------
# 状态流转：开始 / 结团 / 取消
# --------------------------------------------------------------------------


def refresh_game(game: Game, *, now=None) -> Game:
    """惰性刷新单个团：到点自动进入进行中，截止后把未交卡的标出来。"""
    now = now or timezone.now()
    if game.status in OPEN_STATUSES:
        mark_no_card_signups(game, now=now)
        if game.start_at <= now:
            game.status = GAME_RUNNING
            game.save(update_fields=["status", "updated_at"])
    return game


def refresh_due_games(queryset: QuerySet[Game] | None = None, *, now=None) -> int:
    """批量惰性刷新：招募中/已满且已过开团时间的团 → 进行中。返回改了几个。"""
    now = now or timezone.now()
    base = Game.objects.all() if queryset is None else queryset
    ids = list(
        base.filter(status__in=OPEN_STATUSES, start_at__lte=now).values_list("pk", flat=True)
    )
    if not ids:
        return 0
    return Game.objects.filter(pk__in=ids).update(status=GAME_RUNNING, updated_at=now)


def start_game(game: Game) -> Game:
    """GM 手动开始。到 `start_at` 时也会由惰性刷新/定时任务自动进入。"""
    if game.status not in OPEN_STATUSES:
        raise InvalidGameStatus("只有招募中或已满员的团能开始。")
    game.status = GAME_RUNNING
    game.save(update_fields=["status", "updated_at"])
    return game


@transaction.atomic
def finish_game(
    game: Game,
    *,
    attended_signup_ids: list[int] | None = None,
    auto: bool = False,
) -> Game:
    """结团：GM 勾实际到场名单，只有到场者计数。

    **幂等**：已结团的团再调用直接返回，不会重复计数、不会重复发通知。
    计数本身也是按 DB 现状重算的（provider 统计 + `record_play` 的 get_or_create），
    所以即使重复触发也不会把次数算多。
    """
    from apps.accounts.services import maybe_promote_gm
    from apps.charactercards.services import record_play

    if game.status == GAME_FINISHED:
        return game
    if game.status == GAME_CANCELLED:
        raise InvalidGameStatus("已取消的团不能结团。")

    candidates = list(game.signups.filter(status=SIGNUP_ACCEPTED).select_related("player", "card"))
    if auto or attended_signup_ids is None:
        # 自动结团：到场名单 = 全部 accepted。
        attended = candidates
    else:
        wanted = {int(pk) for pk in attended_signup_ids}
        unknown = wanted - {record.pk for record in candidates}
        if unknown:
            raise InvalidSignupStatus("勾选的到场名单中包含未在正式名单内的成员。")
        attended = [record for record in candidates if record.pk in wanted]

    if not attended:
        # 零到场的团不算「跑过」：它既不产生任何计数，又能被 GM 用来刷评价延迟锁
        # （reviews 17.2 时间锁靠「之后又结了几个团」计数，W3 红队复现）。
        # 自动结团那条路径在 `auto_close_games` 里就把这种团筛掉了，不会走到这里。
        raise NoAttendee()

    attended_ids = {record.pk for record in attended}
    for record in candidates:
        should = record.pk in attended_ids
        if record.attended != should:
            record.attended = should
            record.save(update_fields=["attended", "updated_at"])

    now = timezone.now()
    game.status = GAME_FINISHED
    game.finished_at = now
    game.auto_closed = auto
    game.save(update_fields=["status", "finished_at", "auto_closed", "updated_at"])

    # 副作用：只有到场者计数（团次数 / 卡的参团记录 / GM 主持次数 / 自动晋升）
    for record in attended:
        if record.card_id:
            record_play(record.card, game, played_at=now)

    # 卡片重算：两侧都要刷，**参与者全员刷**，且必须排在自动晋升之前
    # （`maybe_promote_gm` 读的是玩家卡的缓存字段 `games_played`）。
    # 评价统计只计「已过延迟」的评价（architecture 第 10 / 17.2 节），而延迟按
    # 「这个人之后又参加了几个团」算 —— 作为 PL 到场的这一个团，同样可能解锁他
    # 作为 GM 收到的旧评价，反之亦然；只刷一侧会让缓存字段长期停在旧值。
    for member in (game.gm, *(record.player for record in attended)):
        refresh_member_cards(member)

    for record in attended:
        maybe_promote_gm(record.player)

    payload = {"game_title": game.title, "auto": auto}
    notify(game.gm, events.REVIEW_OPENED, target=game, payload=payload)
    for record in attended:
        notify(record.player, events.REVIEW_OPENED, target=game, payload=payload)
    if auto:
        notify(
            game.gm,
            events.AUTO_CLOSE_WARNING,
            target=game,
            payload={"game_title": game.title, "message": "系统已按自动结团天数替你结团"},
        )
    return game


@transaction.atomic
def cancel_game(game: Game, *, reason: str) -> Game:
    """取消团：须填理由；取消团不计入任何次数。

    已交的卡保留在 PL 的卡列表里，但不记参团（本函数不调用 `record_play`）。
    """
    reason = (reason or "").strip()
    if not reason:
        raise ReasonRequired("取消团时须填写理由。")
    if game.status == GAME_FINISHED:
        raise InvalidGameStatus("已结团的团不能取消。")
    if game.status == GAME_CANCELLED:
        return game

    affected = list(game.signups.filter(status__in=ACTIVE_STATUSES).select_related("player"))
    game.status = GAME_CANCELLED
    game.cancel_reason = reason
    game.save(update_fields=["status", "cancel_reason", "updated_at"])

    for record in affected:
        refresh_member_cards(record.player)
        notify(
            record.player,
            events.SIGNUP_RESULT,
            target=game,
            payload={"game_title": game.title, "kind": "game_cancelled", "reason": reason},
        )
    refresh_member_cards(game.gm)
    return game


# --------------------------------------------------------------------------
# 场次
# --------------------------------------------------------------------------


def _assert_session_index_free(game: Game, index: int, *, exclude_pk: int | None = None) -> None:
    """(game, index) 上有唯一约束；不先查就会把 IntegrityError 冒成 500。"""
    queryset = Session.objects.filter(game=game, index=index)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise SessionIndexTaken()


def create_session(game: Game, *, index: int, label: str = "", held_at=None) -> Session:
    _assert_session_index_free(game, index)
    return Session.objects.create(game=game, index=index, label=label, held_at=held_at)


def update_session(session: Session, **fields) -> Session:
    """改场次。序号冲突走 400，不放任 IntegrityError 变成 500。"""
    if fields.get("index") is not None:
        _assert_session_index_free(session.game, fields["index"], exclude_pk=session.pk)
    for key, value in fields.items():
        setattr(session, key, value)
    session.save()
    return session


# --------------------------------------------------------------------------
# 定时任务（management command `games_autoclose` 调用）
# --------------------------------------------------------------------------


def send_card_deadline_reminders(*, now=None) -> int:
    """交卡截止前 24 小时提醒未交卡的人；每个团只发一次。"""
    now = now or timezone.now()
    games = Game.objects.filter(
        status__in=OPEN_STATUSES,
        requires_card=True,
        card_deadline__gt=now,
        card_deadline__lte=now + REMINDER_LEAD,
        card_deadline_reminded_at__isnull=True,
    )
    sent = 0
    for game in games:
        for record in game.signups.filter(status=SIGNUP_PENDING).select_related("player"):
            notify(
                record.player,
                events.CARD_DEADLINE_REMINDER,
                target=game,
                payload={"game_title": game.title, "card_deadline": game.card_deadline.isoformat()},
            )
            sent += 1
        game.card_deadline_reminded_at = now
        game.save(update_fields=["card_deadline_reminded_at", "updated_at"])
    return sent


def send_start_reminders(*, now=None) -> int:
    """开团前 24 小时提醒 GM 与已成功报团的人；每个团只发一次。"""
    now = now or timezone.now()
    games = Game.objects.filter(
        status__in=(*OPEN_STATUSES, GAME_RUNNING),
        start_at__gt=now,
        start_at__lte=now + REMINDER_LEAD,
        start_reminded_at__isnull=True,
    ).select_related("gm")
    sent = 0
    for game in games:
        payload = {"game_title": game.title, "start_at": game.start_at.isoformat()}
        notify(game.gm, events.GAME_START_REMINDER, target=game, payload=payload)
        sent += 1
        for record in accepted_roster(game):
            notify(record.player, events.GAME_START_REMINDER, target=game, payload=payload)
            sent += 1
        game.start_reminded_at = now
        game.save(update_fields=["start_reminded_at", "updated_at"])
    return sent


def send_close_reminders(*, now=None) -> int:
    """开团时间 + 自动结团提醒天数（默认 3）后提醒 GM 结团；每个团只发一次。"""
    now = now or timezone.now()
    config = get_config()
    threshold = now - timedelta(days=config.auto_close_reminder_days)
    games = Game.objects.filter(
        status=GAME_RUNNING, start_at__lte=threshold, close_reminded_at__isnull=True
    ).select_related("gm")
    sent = 0
    for game in games:
        notify(
            game.gm,
            events.GAME_CLOSE_REMINDER,
            target=game,
            payload={
                "game_title": game.title,
                "auto_close_days": config.auto_close_days,
            },
        )
        game.close_reminded_at = now
        game.save(update_fields=["close_reminded_at", "updated_at"])
        sent += 1
    return sent


def auto_close_games(*, now=None) -> int:
    """开团时间 + 自动结团天数（默认 7）后自动结团，到场名单 = 全部 accepted。"""
    now = now or timezone.now()
    config = get_config()
    threshold = now - timedelta(days=config.auto_close_days)
    games = list(
        Game.objects.filter(
            status__in=(*OPEN_STATUSES, GAME_RUNNING), start_at__lte=threshold
        ).select_related("gm")
    )
    closed = 0
    for game in games:
        # 零到场的团不能结（`finish_game` 会抛 `no_attendee`）：它会一直停在进行中，
        # 由 GM 自己取消。自动流程在这里就筛掉，免得每轮都撞一次异常。
        if not game.signups.filter(status=SIGNUP_ACCEPTED).exists():
            continue
        finish_game(game, auto=True)
        closed += 1
    return closed


def run_autoclose_cycle(*, now=None) -> dict:
    """定时任务的一轮：刷新状态 → 三种提醒 → 自动结团。返回各步条数。"""
    now = now or timezone.now()
    result = {
        "refreshed": refresh_due_games(now=now),
        "card_deadline_reminders": send_card_deadline_reminders(now=now),
        "start_reminders": send_start_reminders(now=now),
        "no_card_marked": 0,
        "close_reminders": send_close_reminders(now=now),
        "auto_closed": auto_close_games(now=now),
    }
    # 注意要带上 GAME_RUNNING：本轮第一步 `refresh_due_games` 已经把到点的团刷成
    # 进行中，只扫 OPEN_STATUSES 的话这些团里未交卡的人永远不会被标出来。
    for game in Game.objects.filter(
        status__in=(*OPEN_STATUSES, GAME_RUNNING), requires_card=True
    ):
        result["no_card_marked"] += mark_no_card_signups(game, now=now)
    return result


# --------------------------------------------------------------------------
# 反向接线：profiles 统计 provider / charactercards 的卡可见性与团详情
# --------------------------------------------------------------------------


def player_games_played(user) -> int:
    """作为 PL 实际到场且团已结团的次数（GM 自动晋升也用这个口径）。"""
    return Signup.objects.filter(
        player=user, attended=True, status=SIGNUP_ACCEPTED, game__status=GAME_FINISHED
    ).count()


def gm_games_hosted(user) -> int:
    return Game.objects.filter(gm=user, status=GAME_FINISHED).count()


def player_stats_provider(user) -> dict:
    return {"games_played": player_games_played(user)}


def gm_stats_provider(user) -> dict:
    return {"games_hosted": gm_games_hosted(user)}


def gm_can_view_submitted_card(user, card) -> bool:
    """同团 GM 可以下载 PL 交上来的卡（charactercards 的 file access checker）。

    只认「确实交到这个 GM 手上」的报名（已交卡待审 / 成功报团），
    不因为公开与否放宽，也不让别的 GM 看别人团里的卡。
    """
    if not getattr(user, "is_authenticated", False):
        return False
    return Signup.objects.filter(
        card=card, game__gm=user, status__in=(SIGNUP_SUBMITTED, SIGNUP_ACCEPTED)
    ).exists()


def play_detail_provider(game_ids) -> dict:
    """给角色卡的「跑过的团」补团名与时间（charactercards 只存 game_id）。"""
    games = Game.objects.filter(pk__in=list(game_ids)).values(
        "pk", "title", "start_at", "finished_at"
    )
    return {
        row["pk"]: {
            "title": row["title"],
            "start_at": row["start_at"],
            "finished_at": row["finished_at"],
        }
        for row in games
    }
