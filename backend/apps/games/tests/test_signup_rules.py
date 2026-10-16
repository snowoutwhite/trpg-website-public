"""报名规则：门槛与无档位、满员、禁言、GM 本人、战役后续团。"""

from __future__ import annotations

import pytest

from apps.games import services
from apps.games.models import (
    GAME_CLOSED_SIGNUP,
    GAME_RECRUITING,
    SIGNUP_ACCEPTED,
    SIGNUP_PENDING,
    Game,
    Signup,
)
from apps.profiles import levels
from apps.profiles.services import ensure_player_card

from .conftest import soon

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/games/"


def signup_url(game: Game) -> str:
    return f"/api/v1/games/{game.pk}/signup/"


def set_player_stats(user, *, games_played=0, level=""):
    card = ensure_player_card(user)
    card.games_played = games_played
    card.level = level
    card.save(update_fields=["games_played", "level", "updated_at"])
    return card


# --------------------------------------------------------------------------
# 放团
# --------------------------------------------------------------------------


def test_非GM不能放团(api_client, user_factory):
    api_client.force_authenticate(user_factory())
    response = api_client.post(
        LIST_URL, {"title": "我要开团", "start_at": soon(days=3).isoformat()}, format="json"
    )
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_gm"


def test_禁言者不能放团(api_client, gm_factory):
    gm = gm_factory()
    gm.is_muted = True
    gm.save(update_fields=["is_muted"])
    api_client.force_authenticate(gm)

    response = api_client.post(
        LIST_URL, {"title": "禁言团", "start_at": soon(days=3).isoformat()}, format="json"
    )
    assert response.status_code == 403


def test_人数范围非法被拒(gm_factory):
    with pytest.raises(services.InvalidPlayerRange):
        services.create_game(
            gm_factory(), title="人数颠倒", start_at=soon(days=3), min_players=5, max_players=3
        )


def test_交卡截止不得晚于开团时间(api_client, gm_factory):
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        LIST_URL,
        {
            "title": "截止太晚",
            "start_at": soon(days=3).isoformat(),
            "card_deadline": soon(days=4).isoformat(),
        },
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_deadline_after_start"


def test_交卡截止默认等于开团时间(game_factory):
    game = game_factory()
    assert game.card_deadline == game.start_at


def test_战役后续团默认沿用前团人数(game_factory, gm_factory):
    gm = gm_factory()
    first = game_factory(gm, min_players=3, max_players=4)
    second = services.create_game(
        gm, title="西征其二", start_at=soon(days=30), campaign_prev=first
    )
    assert (second.min_players, second.max_players) == (3, 4)


def test_预设标签已随数据迁移建好():
    from apps.games.models import Tag

    presets = set(Tag.objects.filter(is_preset=True).values_list("name", flat=True))
    assert presets == {"战役", "西征"}


def test_标签接口可搜索(api_client):
    response = api_client.get("/api/v1/games/tags/?q=战")
    assert response.status_code == 200
    assert [row["name"] for row in response.json()["results"]] == ["战役"]


# --------------------------------------------------------------------------
# 报名门槛
# --------------------------------------------------------------------------


def test_团次数门槛不足被拒(game_factory, user_factory):
    game = game_factory(min_play_count=3)
    player = user_factory()
    set_player_stats(player, games_played=1)

    with pytest.raises(services.ThresholdNotMet):
        services.signup(game, player)


def test_团次数达标可报名(game_factory, user_factory):
    game = game_factory(min_play_count=3)
    player = user_factory()
    set_player_stats(player, games_played=3)

    assert services.signup(game, player).status == SIGNUP_PENDING


def test_无档位者不能报设了赞级别门槛的团(api_client, game_factory, user_factory):
    """业务规则与安全约束。"""
    game = game_factory(min_level=levels.MOSTLY_POSITIVE)
    player = user_factory()
    set_player_stats(player, games_played=99, level="")  # 评价数不足 → 无档位

    api_client.force_authenticate(player)
    response = api_client.post(signup_url(game))
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "threshold_not_met"
    assert "档位" in response.json()["error"]["message"]


def test_档位不够高被拒而够高可报(game_factory, user_factory):
    game = game_factory(min_level=levels.MOSTLY_POSITIVE)
    low = user_factory()
    set_player_stats(low, level=levels.MIXED)
    high = user_factory()
    set_player_stats(high, level=levels.OVERWHELMINGLY_POSITIVE)

    with pytest.raises(services.ThresholdNotMet):
        services.signup(game, low)
    assert services.signup(game, high).status == SIGNUP_PENDING


def test_站主关闭赞功能后门槛失效(game_factory, user_factory, site_config):
    """关赞时门槛字段同时失效，已设门槛的团视为无门槛。"""
    game = game_factory(min_level=levels.OVERWHELMINGLY_POSITIVE, min_play_count=10)
    player = user_factory()
    set_player_stats(player, games_played=0, level="")

    site_config.like_feature_enabled = False
    site_config.save()

    assert services.effective_thresholds(game) == (None, "")
    assert services.signup(game, player).status == SIGNUP_PENDING


# --------------------------------------------------------------------------
# 报名的其他约束
# --------------------------------------------------------------------------


def test_GM不能报名自己的团(game_factory):
    game = game_factory()
    with pytest.raises(services.CannotSignupOwnGame):
        services.signup(game, game.gm)


def test_禁言者不能报名(api_client, game_factory, user_factory):
    game = game_factory()
    player = user_factory()
    player.is_muted = True
    player.save(update_fields=["is_muted"])

    api_client.force_authenticate(player)
    assert api_client.post(signup_url(game)).status_code == 403


def test_不能重复报名(game_factory, user_factory):
    game = game_factory()
    player = user_factory()
    services.signup(game, player)
    with pytest.raises(services.AlreadySignedUp):
        services.signup(game, player)


def test_满员后关闭报名扩容可重开(game_factory, user_factory):
    game = game_factory(max_players=2)
    first, second, third = user_factory(), user_factory(), user_factory()

    services.signup(game, first)
    services.signup(game, second)
    game.refresh_from_db()
    assert game.status == GAME_CLOSED_SIGNUP

    with pytest.raises(services.GameFull):
        services.signup(game, third)

    services.expand_capacity(game, max_players=3)
    game.refresh_from_db()
    assert game.status == GAME_RECRUITING
    assert services.signup(game, third).status == SIGNUP_PENDING


def test_待交卡和待审都算占位(game_factory, user_factory, card_factory):
    """满员口径：accepted + pending + submitted 都算占着位置。"""
    game = game_factory(max_players=2, signup_mode="pool_review")
    one, two = user_factory(), user_factory()
    record = services.signup(game, one)
    services.submit_card(record, card_factory(one))  # 变成 submitted
    services.signup(game, two)

    game.refresh_from_db()
    assert game.occupied_seats == 2
    assert game.is_full
    with pytest.raises(services.GameFull):
        services.signup(game, user_factory())


def test_战役后续团可限定前团到场成员(game_factory, gm_factory, user_factory, card_factory):
    gm = gm_factory()
    first = game_factory(gm, start_at=soon(days=1))
    veteran, outsider = user_factory(), user_factory()
    record = services.signup(first, veteran)
    services.submit_card(record, card_factory(veteran))
    services.finish_game(first, attended_signup_ids=[record.pk])

    second = services.create_game(
        gm,
        title="西征其二",
        start_at=soon(days=30),
        campaign_prev=first,
        restrict_to_prev_members=True,
    )
    assert services.signup(second, veteran).status == SIGNUP_PENDING
    with pytest.raises(services.NotPrevMember):
        services.signup(second, outsider)


def test_被GM移除后不能自己报回来(game_factory, user_factory):
    game = game_factory()
    player = user_factory()
    record = services.signup(game, player)
    services.gm_remove(record, reason="放鸽子")

    with pytest.raises(services.SignupClosedForYou):
        services.signup(game, player)


def test_报名后GM收到站内通知(game_factory, user_factory):
    from apps.notifications import events
    from apps.notifications.models import Notification

    game = game_factory()
    player = user_factory()
    services.signup(game, player)

    note = Notification.objects.get(recipient=game.gm, event=events.SIGNUP_RECEIVED)
    assert note.actor_id == player.pk
    assert note.payload["game_title"] == game.title


def test_报名顺序单调递增(game_factory, user_factory):
    game = game_factory()
    orders = [services.signup(game, user_factory()).order for _ in range(3)]
    assert orders == [1, 2, 3]
    assert list(Signup.objects.filter(game=game).values_list("order", flat=True)) == [1, 2, 3]


def test_报名进行中的团会被拒(game_factory, user_factory):
    """到了开团时间的团会惰性流转成进行中，不再接受报名。"""
    game = game_factory(start_at=soon(seconds=1))
    Game.objects.filter(pk=game.pk).update(start_at=soon(days=-1), card_deadline=soon(days=-1))
    game.refresh_from_db()

    with pytest.raises(services.GameNotRecruiting):
        services.signup(game, user_factory())


def test_免交卡团先到先得报名即成功报团(game_factory, user_factory):
    game = game_factory(requires_card=False)
    assert services.signup(game, user_factory()).status == SIGNUP_ACCEPTED


def test_免交卡团PL池模式仍需GM审批(game_factory, user_factory):
    """「报名通过即成功报团」：PL 池模式里那个「通过」就是 GM 审批（实现解读）。"""
    game = game_factory(requires_card=False, signup_mode="pool_review")
    record = services.signup(game, user_factory())
    assert record.status == "submitted"

    services.review_signup(record, approved=True)
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED
