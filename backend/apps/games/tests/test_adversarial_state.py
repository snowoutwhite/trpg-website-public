"""对抗测试：状态机绕过、结团幂等、容量与门槛。

攻击假设：
1. 截止那一分钟到底能不能交卡？截止后呢？团开始/结团/取消之后呢？
2. `card_deadline` 能不能被改到晚于 `start_at`？`card_deadline` 传 null 会怎样？
3. 结团时到场名单塞「非本团 / 被拒 / GM 自己 / 重复 id」会怎样？
4. 重复结团会不会把团次数、卡的参团次数、GM 主持次数、自动晋升算两遍？
5. 结团/取消之后，GM 还能不能靠审批、移除、确认退出把正式名单改掉？
6. 扩容 / 缩容 / min>max / 0 / 巨大值。
7. 先到先得团最后一个位置的 check-then-act 竞态。
8. 门槛：关赞开关、无档位者、缓存字段能不能伪造、`campaign_prev` 能不能蹭别人的团。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.charactercards.models import CardPlayRecord
from apps.games import services
from apps.games.models import (
    GAME_CANCELLED,
    GAME_CLOSED_SIGNUP,
    GAME_FINISHED,
    GAME_RECRUITING,
    GAME_RUNNING,
    SIGNUP_ACCEPTED,
    SIGNUP_NO_CARD,
    SIGNUP_PENDING,
    SIGNUP_REJECTED,
    Game,
    Signup,
)

from .conftest import ago, soon

pytestmark = pytest.mark.django_db


def _same_moment(**kwargs) -> dict:
    """开团时间与交卡截止取同一个瞬间。

    两次 `timezone.now()` 会差出几微秒，足以让「截止不得晚于开团」误判，
    所以必须只取一次。
    """
    moment = timezone.now() + timedelta(**kwargs)
    return {"start_at": moment, "card_deadline": moment}


def _move_to_past(game: Game, *, hours: int = 1) -> Game:
    """把团的开团时间与交卡截止挪到过去（造「已开团」的局面）。"""
    game.start_at = timezone.now() - timedelta(hours=hours)
    game.card_deadline = game.start_at
    game.save(update_fields=["start_at", "card_deadline"])
    return game


def _open_game(game_factory, **kwargs):
    """造一个还在招募中的团（开团时间与截止都在未来，且是同一瞬间）。"""
    kwargs.update({k: v for k, v in _same_moment(days=1).items() if k not in kwargs})
    return game_factory(**kwargs)


def _finished_game(game_factory, user_factory, card_factory, **kwargs):
    """造一个「已开团、有一名交过卡的 PL」的团，尚未结团。"""
    game = _open_game(game_factory, **kwargs)
    player = user_factory(nickname="到场的人")
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    _move_to_past(game)
    record.refresh_from_db()
    return game, player, record


# --------------------------------------------------------------------------
# 1. 交卡截止的分钟边界
# --------------------------------------------------------------------------


def test_截止那一刻仍可交卡截止之后不行(game_factory, user_factory, card_factory):
    """「精确到分钟」的边界：等于 deadline 放行，超过一秒即拒。"""
    deadline = timezone.now() + timedelta(days=1)
    game = game_factory(start_at=deadline, card_deadline=deadline)
    player = user_factory()
    record = services.signup(game, player)
    card = card_factory(player)

    services.submit_card(record, card, now=deadline)  # 等于截止：放行
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED

    with pytest.raises(services.CardDeadlinePassed):
        services.submit_card(record, card, now=deadline + timedelta(seconds=1))


def test_截止后交卡接口被拒且不改状态(api_client, game_factory, user_factory, card_factory):
    game = _open_game(game_factory)
    player = user_factory()
    record = services.signup(game, player)
    card = card_factory(player)
    game.card_deadline = ago(minutes=1)
    game.save(update_fields=["card_deadline"])

    api_client.force_authenticate(player)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/submit-card/", {"card_id": card.pk}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_deadline_passed"
    record.refresh_from_db()
    assert record.status == SIGNUP_PENDING
    assert record.card_id is None


@pytest.mark.parametrize("terminal", ["finish", "cancel"])
def test_结团或取消后不能再报名不能再交卡(
    api_client, game_factory, user_factory, card_factory, terminal
):
    game = _open_game(game_factory)
    player = user_factory()
    services.signup(game, player)
    card = card_factory(player)
    newcomer = user_factory()

    if terminal == "finish":
        # W5：结团必须至少有一位到场 PL（`no_attendee`），所以先把这位交上卡。
        record = services.signup(game, newcomer_card_owner := user_factory())
        services.submit_card(record, card_factory(newcomer_card_owner))
        record.refresh_from_db()
        services.finish_game(game, attended_signup_ids=[record.pk])
    else:
        services.cancel_game(game, reason="不跑了")
    game.refresh_from_db()

    api_client.force_authenticate(player)
    submit = api_client.post(
        f"/api/v1/games/{game.pk}/submit-card/", {"card_id": card.pk}, format="json"
    )
    assert submit.status_code == 400
    assert submit.json()["error"]["code"] == "invalid_game_status"

    api_client.force_authenticate(newcomer)
    signup = api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json")
    assert signup.status_code == 400
    assert signup.json()["error"]["code"] == "game_not_recruiting"
    assert Signup.objects.filter(game=game, player=newcomer).count() == 0


# --------------------------------------------------------------------------
# 2. 时间字段
# --------------------------------------------------------------------------


def test_截止不得被改到晚于开团(api_client, game_factory):
    game = game_factory(start_at=soon(days=5))
    api_client.force_authenticate(game.gm)
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/", {"card_deadline": soon(days=6).isoformat()}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_deadline_after_start"
    game.refresh_from_db()
    assert game.card_deadline == game.start_at


def test_把开团时间提前到截止之前也会被拦(api_client, game_factory):
    game = _open_game(game_factory, **_same_moment(days=5))
    api_client.force_authenticate(game.gm)
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/", {"start_at": soon(days=1).isoformat()}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_deadline_after_start"


def test_PATCH截止时间传null不得500(api_client, game_factory):
    """`card_deadline` 序列化器允许 null，但 services 会拿 None 去比大小。"""
    game = game_factory(start_at=soon(days=5))
    api_client.force_authenticate(game.gm)
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/", {"card_deadline": None}, format="json"
    )
    assert response.status_code != 500, "PATCH card_deadline=null 触发了 500"
    game.refresh_from_db()
    assert game.card_deadline is not None


def test_开团时间改到过去后团进入进行中且不能再报名(api_client, game_factory, user_factory):
    game = _open_game(game_factory, **_same_moment(days=5))
    past = timezone.now() - timedelta(days=1)
    api_client.force_authenticate(game.gm)
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/",
        {"start_at": past.isoformat(), "card_deadline": past.isoformat()},
        format="json",
    )
    assert response.status_code == 200

    stranger = user_factory()
    api_client.force_authenticate(stranger)
    assert api_client.get(f"/api/v1/games/{game.pk}/").status_code == 200
    game.refresh_from_db()
    assert game.status == GAME_RUNNING
    assert (
        api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json").status_code == 400
    )


def test_已结团的团不能再PATCH(api_client, game_factory, user_factory, card_factory):
    # W5：结团必须至少有一位到场 PL，所以先凑一位。
    game, _player, record = _finished_game(game_factory, user_factory, card_factory)
    services.finish_game(game, attended_signup_ids=[record.pk])
    api_client.force_authenticate(game.gm)
    response = api_client.patch(f"/api/v1/games/{game.pk}/", {"title": "改"}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_game_status"


# --------------------------------------------------------------------------
# 3. 结团的到场名单
# --------------------------------------------------------------------------


def test_到场名单塞非本团用户被拒(api_client, game_factory, user_factory, card_factory):
    game, player, record = _finished_game(game_factory, user_factory, card_factory)
    other_game = game_factory()
    outsider = user_factory()
    foreign = services.signup(other_game, outsider)

    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/finish/",
        {"attended_signup_ids": [record.pk, foreign.pk]},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_signup_status"
    game.refresh_from_db()
    record.refresh_from_db()
    foreign.refresh_from_db()
    assert game.status != GAME_FINISHED
    assert record.attended is False
    assert foreign.attended is False


def test_到场名单塞被拒者与未交卡者被拒(api_client, game_factory, user_factory, card_factory):
    game = _open_game(game_factory, max_players=5)
    player = user_factory()
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    rejected_pl = user_factory()
    rejected = services.signup(game, rejected_pl)
    services.review_signup(rejected, approved=False, note="不收")
    _move_to_past(game)

    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/finish/",
        {"attended_signup_ids": [record.pk, rejected.pk]},
        format="json",
    )
    assert response.status_code == 400
    game.refresh_from_db()
    assert game.status != GAME_FINISHED


def test_到场名单塞GM自己的用户id无效(api_client, game_factory, user_factory, card_factory):
    """signup id 与 user id 是两个命名空间：拿 GM 的 user id 冒充 signup id 必须失败。"""
    game, _, record = _finished_game(game_factory, user_factory, card_factory)
    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/finish/",
        {"attended_signup_ids": [game.gm_id + 100000]},
        format="json",
    )
    assert response.status_code == 400
    game.refresh_from_db()
    assert game.status != GAME_FINISHED


def test_结团必须给到场名单(api_client, game_factory, user_factory, card_factory):
    game, _, _ = _finished_game(game_factory, user_factory, card_factory)
    api_client.force_authenticate(game.gm)
    response = api_client.post(f"/api/v1/games/{game.pk}/finish/", {}, format="json")
    assert response.status_code == 400
    game.refresh_from_db()
    assert game.status != GAME_FINISHED


# --------------------------------------------------------------------------
# 4. 结团幂等
# --------------------------------------------------------------------------


def test_重复结团不重复计数(api_client, game_factory, user_factory, card_factory, site_config):
    """团次数 / 卡的参团记录 / GM 主持次数 / 自动晋升，重复触发都不得算多。"""
    from apps.notifications.models import Notification
    from apps.profiles.services import ensure_gm_card, ensure_player_card

    game, player, record = _finished_game(game_factory, user_factory, card_factory)
    card = record.card

    api_client.force_authenticate(game.gm)
    path = f"/api/v1/games/{game.pk}/finish/"
    first = api_client.post(path, {"attended_signup_ids": [record.pk]}, format="json")
    assert first.status_code == 200

    notifications_after_first = Notification.objects.count()
    card.refresh_from_db()
    assert card.play_count == 1
    assert ensure_player_card(player).games_played == 1
    assert ensure_gm_card(game.gm).games_hosted == 1

    for _ in range(3):
        again = api_client.post(path, {"attended_signup_ids": [record.pk]}, format="json")
        assert again.status_code == 200

    card.refresh_from_db()
    assert card.play_count == 1, "重复结团把卡的参团次数算多了"
    assert CardPlayRecord.objects.filter(card=card, game_id=game.pk).count() == 1
    assert ensure_player_card(player).games_played == 1, "重复结团把团次数算多了"
    assert ensure_gm_card(game.gm).games_hosted == 1, "重复结团把 GM 主持次数算多了"
    assert Notification.objects.count() == notifications_after_first, "重复结团重复发了通知"

    game.refresh_from_db()
    assert game.status == GAME_FINISHED


def test_重复结团不能改到场名单(api_client, game_factory, user_factory, card_factory):
    """第二次结团即便换了名单，也必须被幂等短路，不得翻 attended。"""
    game, _, record = _finished_game(game_factory, user_factory, card_factory)
    api_client.force_authenticate(game.gm)
    path = f"/api/v1/games/{game.pk}/finish/"
    assert api_client.post(path, {"attended_signup_ids": [record.pk]}, format="json").status_code == 200
    assert api_client.post(path, {"attended_signup_ids": []}, format="json").status_code == 200
    record.refresh_from_db()
    assert record.attended is True


def test_取消后不能结团结团后不能取消(api_client, game_factory, user_factory, card_factory):
    game, _, record = _finished_game(game_factory, user_factory, card_factory)
    api_client.force_authenticate(game.gm)

    assert api_client.post(f"/api/v1/games/{game.pk}/cancel/", {"reason": "散团"}, format="json").status_code == 200
    finish = api_client.post(
        f"/api/v1/games/{game.pk}/finish/", {"attended_signup_ids": [record.pk]}, format="json"
    )
    assert finish.status_code == 400
    assert finish.json()["error"]["code"] == "invalid_game_status"
    game.refresh_from_db()
    assert game.status == GAME_CANCELLED
    record.refresh_from_db()
    assert record.attended is False


def test_已结团的团不能取消也不会回滚计数(api_client, game_factory, user_factory, card_factory):
    from apps.profiles.services import ensure_player_card

    game, player, record = _finished_game(game_factory, user_factory, card_factory)
    api_client.force_authenticate(game.gm)
    assert api_client.post(
        f"/api/v1/games/{game.pk}/finish/", {"attended_signup_ids": [record.pk]}, format="json"
    ).status_code == 200

    cancel = api_client.post(f"/api/v1/games/{game.pk}/cancel/", {"reason": "反悔"}, format="json")
    assert cancel.status_code == 400
    game.refresh_from_db()
    assert game.status == GAME_FINISHED
    assert ensure_player_card(player).games_played == 1


def test_取消团不计任何次数(api_client, game_factory, user_factory, card_factory):
    from apps.profiles.services import ensure_gm_card, ensure_player_card

    game, player, record = _finished_game(game_factory, user_factory, card_factory)
    services.cancel_game(game, reason="GM 有事")
    record.refresh_from_db()
    assert record.attended is False
    assert ensure_player_card(player).games_played == 0
    assert ensure_gm_card(game.gm).games_hosted == 0
    assert record.card.play_count == 0


def test_取消必须写理由(api_client, game_factory):
    game = game_factory()
    api_client.force_authenticate(game.gm)
    for payload in ({}, {"reason": ""}, {"reason": "   "}):
        response = api_client.post(f"/api/v1/games/{game.pk}/cancel/", payload, format="json")
        assert response.status_code == 400
    game.refresh_from_db()
    assert game.status == GAME_RECRUITING


# --------------------------------------------------------------------------
# 5. 结团 / 取消之后的名单改动
# --------------------------------------------------------------------------


def test_结团后GM不能再把人审批进正式名单(api_client, game_factory, user_factory, card_factory):
    """结团后名单必须冻结：否则 GM 能事后给人「塞进团」拿到同团可见性与评价资格。"""
    game = _open_game(game_factory, max_players=5)
    player = user_factory()
    attended = services.signup(game, player)
    services.submit_card(attended, card_factory(player))
    latecomer = user_factory(nickname="事后被塞进来的人")
    late = services.signup(game, latecomer)
    assert late.status == SIGNUP_PENDING
    _move_to_past(game)

    services.finish_game(game, attended_signup_ids=[attended.pk])
    game.refresh_from_db()

    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{late.pk}/review/",
        {"approved": True, "note": "补一个"},
        format="json",
    )
    assert response.status_code == 400, "结团后 GM 还能改正式名单"
    assert response.json()["error"]["code"] == "invalid_game_status"
    late.refresh_from_db()
    assert late.status != SIGNUP_ACCEPTED

    # 后果验证：没进正式名单 → 拿不到 roster
    api_client.force_authenticate(latecomer)
    assert api_client.get(f"/api/v1/games/{game.pk}/roster/").status_code == 403


def test_结团后GM不能把到场者移出(api_client, game_factory, user_factory, card_factory):
    """移出会让 `player_games_played` 的口径与已落库的缓存/参团记录对不上。"""
    from apps.profiles.services import ensure_player_card

    game, player, record = _finished_game(game_factory, user_factory, card_factory)
    services.finish_game(game, attended_signup_ids=[record.pk])
    assert ensure_player_card(player).games_played == 1

    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/remove/", {"reason": "事后反悔"}, format="json"
    )
    assert response.status_code == 400, "结团后 GM 还能把到场者移出"
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED
    assert services.player_games_played(player) == 1


def test_取消后GM不能再处置报名(api_client, game_factory, user_factory, card_factory):
    game, _, record = _finished_game(game_factory, user_factory, card_factory)
    services.cancel_game(game, reason="散")
    api_client.force_authenticate(game.gm)
    for path, payload in (
        ("review/", {"approved": False, "note": "拒"}),
        ("remove/", {"reason": "踢"}),
    ):
        response = api_client.post(
            f"/api/v1/games/{game.pk}/signups/{record.pk}/{path}", payload, format="json"
        )
        assert response.status_code == 400, f"取消后 {path} 仍可执行"
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED


def test_结团后不能再开始(api_client, game_factory, user_factory, card_factory):
    game, _, record = _finished_game(game_factory, user_factory, card_factory)
    services.finish_game(game, attended_signup_ids=[record.pk])
    api_client.force_authenticate(game.gm)
    response = api_client.post(f"/api/v1/games/{game.pk}/start/", {}, format="json")
    assert response.status_code == 400
    game.refresh_from_db()
    assert game.status == GAME_FINISHED


def test_结团后不能退出(api_client, game_factory, user_factory, card_factory):
    game, player, record = _finished_game(game_factory, user_factory, card_factory)
    services.finish_game(game, attended_signup_ids=[record.pk])
    api_client.force_authenticate(player)
    response = api_client.post(f"/api/v1/games/{game.pk}/withdraw/", {}, format="json")
    assert response.status_code == 400
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED


# --------------------------------------------------------------------------
# 6. 容量
# --------------------------------------------------------------------------


def test_扩容后重新开放报名(api_client, game_factory, user_factory):
    game = game_factory(max_players=1)
    first = user_factory()
    services.signup(game, first)
    game.refresh_from_db()
    assert game.status == GAME_CLOSED_SIGNUP

    second = user_factory()
    api_client.force_authenticate(second)
    blocked = api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json")
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "game_full"

    api_client.force_authenticate(game.gm)
    assert api_client.post(f"/api/v1/games/{game.pk}/expand/", {"max_players": 2}, format="json").status_code == 200
    api_client.force_authenticate(second)
    assert api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json").status_code == 201
    game.refresh_from_db()
    assert game.status == GAME_CLOSED_SIGNUP


def test_缩容到小于已通过人数不会凭空开放报名(api_client, game_factory, user_factory):
    game = game_factory(max_players=3)
    for _ in range(3):
        services.signup(game, user_factory())
    api_client.force_authenticate(game.gm)
    assert api_client.post(f"/api/v1/games/{game.pk}/expand/", {"max_players": 1}, format="json").status_code == 200
    game.refresh_from_db()
    assert game.status == GAME_CLOSED_SIGNUP
    assert game.occupied_seats == 3

    api_client.force_authenticate(user_factory())
    assert api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json").status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"max_players": 0},
        {"max_players": -1},
        {"max_players": "abc"},
        {},
    ],
)
def test_扩容非法值被拒(api_client, game_factory, payload):
    game = game_factory(max_players=5)
    api_client.force_authenticate(game.gm)
    response = api_client.post(f"/api/v1/games/{game.pk}/expand/", payload, format="json")
    assert response.status_code == 400
    game.refresh_from_db()
    assert game.max_players == 5


def test_扩容不能小于最少人数(api_client, game_factory):
    game = game_factory(min_players=3, max_players=5)
    api_client.force_authenticate(game.gm)
    response = api_client.post(f"/api/v1/games/{game.pk}/expand/", {"max_players": 2}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_player_range"


@pytest.mark.parametrize(
    "payload",
    [
        {"min_players": 5, "max_players": 1},
        {"min_players": 0, "max_players": 5},
        {"min_players": -3, "max_players": 5},
    ],
)
def test_放团人数范围非法被拒(api_client, gm_factory, payload):
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {"title": "范围非法团", "start_at": soon(days=3).isoformat(), **payload},
        format="json",
    )
    assert response.status_code == 400
    assert not Game.objects.filter(title="范围非法团").exists()


def test_PATCH把min改到大于max被拒(api_client, game_factory):
    game = game_factory(min_players=1, max_players=3)
    api_client.force_authenticate(game.gm)
    response = api_client.patch(f"/api/v1/games/{game.pk}/", {"min_players": 9}, format="json")
    assert response.status_code == 400
    game.refresh_from_db()
    assert game.min_players == 1


def test_巨大人数不会溢出(api_client, gm_factory):
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {
            "title": "巨团",
            "start_at": soon(days=3).isoformat(),
            "min_players": 1,
            "max_players": 10**12,
        },
        format="json",
    )
    assert response.status_code in (201, 400)
    if response.status_code == 201:
        game = Game.objects.get(title="巨团")
        assert game.is_full is False


# --------------------------------------------------------------------------
# 7. 最后一个位置的 check-then-act 竞态
# --------------------------------------------------------------------------


def test_最后一个位置不会被两个人同时占走(game_factory, user_factory, monkeypatch):
    """模拟竞态：容量检查通过之后、写入之前，另一个请求抢走了最后一位。

    生产用 PostgreSQL 时靠 `select_for_update` 串行化；但开发/测试用的 SQLite
    **不支持行锁，Django 会静默忽略 `select_for_update`**，所以不能只靠锁。
    这里在检查与写入之间注入一次抢占，要求最终占位数不得超过上限。
    """
    game = game_factory(max_players=1)
    rusher = user_factory(nickname="抢先的人")
    loser = user_factory(nickname="慢一步的人")

    original = services._next_order
    state = {"done": False}

    def racing_next_order(target_game):
        if not state["done"]:
            state["done"] = True
            Signup.objects.create(
                game=target_game, player=rusher, order=1, status=SIGNUP_ACCEPTED
            )
        return original(target_game)

    monkeypatch.setattr(services, "_next_order", racing_next_order)

    with pytest.raises(services.GameFull):
        services.signup(game, loser)

    game.refresh_from_db()
    assert game.occupied_seats <= game.max_players, "两个人同时占走了最后一个位置"
    assert not Signup.objects.filter(game=game, player=loser).exists()


# --------------------------------------------------------------------------
# 8. 门槛
# --------------------------------------------------------------------------


def test_关掉赞功能后门槛全部失效(api_client, game_factory, user_factory, site_config):
    game = game_factory(min_play_count=5, min_level="excellent")
    site_config.like_feature_enabled = False
    site_config.save()

    player = user_factory()
    api_client.force_authenticate(player)
    assert api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json").status_code == 201


def test_无档位者不能报设了赞级别门槛的团(api_client, game_factory, user_factory, site_config):
    from apps.profiles.services import ensure_player_card

    game = game_factory(min_level="excellent")
    player = user_factory()
    assert ensure_player_card(player).level == ""

    api_client.force_authenticate(player)
    response = api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json")
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "threshold_not_met"
    assert Signup.objects.filter(game=game, player=player).count() == 0


def test_团次数门槛不能靠改玩家卡伪造(api_client, game_factory, user_factory):
    """`games_played` 是缓存字段，接口上必须只读，否则门槛形同虚设。"""
    from apps.profiles.services import ensure_player_card

    game = game_factory(min_play_count=3)
    player = user_factory()
    api_client.force_authenticate(player)

    for payload in ({"games_played": 99}, {"level": "excellent"}, {"likes": 500}):
        response = api_client.patch("/api/v1/profiles/me/player-card/", payload, format="json")
        assert response.status_code in (200, 400)
    card = ensure_player_card(player)
    assert card.games_played == 0, "玩家卡的团次数被伪造了"
    assert card.level == ""

    response = api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json")
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "threshold_not_met"


def test_门槛达标者可以报名(api_client, game_factory, user_factory, card_factory):
    """正向对照：确认门槛不是把所有人都拦住了。"""
    from apps.profiles.services import ensure_player_card

    prev_game, player, prev_record = _finished_game(game_factory, user_factory, card_factory)
    services.finish_game(prev_game, attended_signup_ids=[prev_record.pk])
    assert ensure_player_card(player).games_played == 1

    game = game_factory(min_play_count=1)
    api_client.force_authenticate(player)
    assert api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json").status_code == 201


def test_战役前团不能指向别人的团(api_client, gm_factory, game_factory):
    other_game = game_factory()
    attacker = gm_factory()
    api_client.force_authenticate(attacker)
    response = api_client.post(
        "/api/v1/games/",
        {
            "title": "蹭别人战役",
            "start_at": soon(days=3).isoformat(),
            "campaign_prev": other_game.pk,
            "restrict_to_prev_members": True,
        },
        format="json",
    )
    assert response.status_code == 400
    assert not Game.objects.filter(title="蹭别人战役").exists()


def test_PATCH也不能把前团改成别人的团(api_client, game_factory):
    mine = game_factory()
    other = game_factory()
    api_client.force_authenticate(mine.gm)
    response = api_client.patch(
        f"/api/v1/games/{mine.pk}/", {"campaign_prev": other.pk}, format="json"
    )
    assert response.status_code == 400
    mine.refresh_from_db()
    assert mine.campaign_prev_id is None


def test_仅限前团成员时未到场者报不进来(api_client, game_factory, user_factory, card_factory):
    prev_game = _open_game(game_factory, max_players=5)
    member = user_factory(nickname="到场的人")
    member_signup = services.signup(prev_game, member)
    services.submit_card(member_signup, card_factory(member))
    absent = user_factory(nickname="报了名但没到场")
    absent_signup = services.signup(prev_game, absent)
    services.submit_card(absent_signup, card_factory(absent))
    _move_to_past(prev_game)
    services.finish_game(prev_game, attended_signup_ids=[member_signup.pk])

    sequel = game_factory(
        gm=prev_game.gm, campaign_prev=prev_game, restrict_to_prev_members=True
    )
    api_client.force_authenticate(absent)
    response = api_client.post(f"/api/v1/games/{sequel.pk}/signup/", {}, format="json")
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_prev_member"

    api_client.force_authenticate(member)
    assert api_client.post(f"/api/v1/games/{sequel.pk}/signup/", {}, format="json").status_code == 201


def test_仅限前团成员且前团未结团时无人能报(api_client, game_factory, user_factory):
    """前团还没结团 → 没有任何 attended=True → 谁都报不进来，而不是谁都能报。"""
    prev_game = game_factory()
    member = user_factory()
    services.signup(prev_game, member)

    sequel = game_factory(
        gm=prev_game.gm, campaign_prev=prev_game, restrict_to_prev_members=True
    )
    api_client.force_authenticate(member)
    response = api_client.post(f"/api/v1/games/{sequel.pk}/signup/", {}, format="json")
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_prev_member"


def test_仅限前团成员但没指定前团时无人能报(api_client, game_factory, user_factory):
    game = game_factory(restrict_to_prev_members=True)
    api_client.force_authenticate(user_factory())
    response = api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json")
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_prev_member"


# --------------------------------------------------------------------------
# 被 GM 处置过的人不能自己报回来
# --------------------------------------------------------------------------


def test_被移出者不能自己报回来(api_client, game_factory, user_factory):
    game = game_factory()
    player = user_factory()
    record = services.signup(game, player)
    services.gm_remove(record, reason="捣乱")

    api_client.force_authenticate(player)
    response = api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json")
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "signup_closed_for_you"


def test_未交卡者不能重复报名占位(api_client, game_factory, user_factory):
    game = _open_game(game_factory)
    player = user_factory()
    services.signup(game, player)
    game.card_deadline = ago(minutes=5)
    game.save(update_fields=["card_deadline"])
    services.mark_no_card_signups(game)
    assert Signup.objects.get(game=game, player=player).status == SIGNUP_NO_CARD

    api_client.force_authenticate(player)
    response = api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json")
    assert response.status_code == 400
    assert Signup.objects.filter(game=game, player=player).count() == 1


def test_审批不能把满员的团挤爆(api_client, game_factory, user_factory):
    """no_card 不占位，审批通过时如果团已满必须拒。"""
    game = _open_game(game_factory, max_players=1)
    late = user_factory()
    late_signup = services.signup(game, late)
    game.card_deadline = ago(minutes=5)
    game.save(update_fields=["card_deadline"])
    services.mark_no_card_signups(game)
    late_signup.refresh_from_db()
    assert late_signup.status == SIGNUP_NO_CARD

    # 位置被另一个人占满
    services.signup(game, user_factory())
    game.refresh_from_db()
    assert game.is_full

    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{late_signup.pk}/review/",
        {"approved": True},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "game_full"
    late_signup.refresh_from_db()
    assert late_signup.status == SIGNUP_NO_CARD
    assert late_signup.status != SIGNUP_REJECTED
