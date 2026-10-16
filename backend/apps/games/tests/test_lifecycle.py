"""状态流转：退出两段、GM 移除、开始、结团（幂等 / 只有到场计数）、取消、自动晋升。"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.games import services
from apps.games.models import (
    GAME_CANCELLED,
    GAME_FINISHED,
    GAME_RUNNING,
    SIGNUP_ACCEPTED,
    SIGNUP_POOL_REVIEW,
    SIGNUP_REMOVED,
    SIGNUP_WITHDRAWN,
    Game,
)
from apps.notifications import events
from apps.notifications.models import Notification
from apps.profiles.services import ensure_player_card, recompute_gm_card, recompute_player_card

from .conftest import ago, soon

pytestmark = pytest.mark.django_db


def accept(game, player, card_factory):
    """让一个人一路走到 accepted。"""
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED
    return record


# --------------------------------------------------------------------------
# 退出两段式
# --------------------------------------------------------------------------


def test_截止前可以直接退出(api_client, signed_up):
    game, player, record = signed_up()
    api_client.force_authenticate(player)
    response = api_client.post(f"/api/v1/games/{game.pk}/withdraw/", {"reason": "临时有事"}, format="json")

    assert response.status_code == 200
    assert response.json()["withdrawn"] is True
    record.refresh_from_db()
    assert record.status == SIGNUP_WITHDRAWN
    assert Notification.objects.filter(recipient=game.gm, event=events.SIGNUP_RESULT).exists()


def test_截止后退出要GM确认(api_client, signed_up, card_factory):
    game, player, record = signed_up()
    services.submit_card(record, card_factory(player))
    Game.objects.filter(pk=game.pk).update(card_deadline=ago(hours=1))
    record.refresh_from_db()

    api_client.force_authenticate(player)
    response = api_client.post(f"/api/v1/games/{game.pk}/withdraw/", {"reason": "生病"}, format="json")

    assert response.status_code == 200
    assert response.json() == {
        **response.json(),
        "withdrawn": False,
        "pending_gm_confirm": True,
    }
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED  # 还没退成
    assert record.withdraw_requested_at is not None

    api_client.force_authenticate(game.gm)
    confirm = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/confirm-withdraw/",
        {"approved": True},
        format="json",
    )
    assert confirm.status_code == 200
    record.refresh_from_db()
    assert record.status == SIGNUP_WITHDRAWN
    assert record.withdraw_requested_at is None
    assert Notification.objects.filter(recipient=player, event=events.SIGNUP_RESULT).exists()


def test_退出后可以重新报名(signed_up):
    game, player, record = signed_up()
    services.withdraw(record)
    again = services.signup(game, player)
    assert again.pk == record.pk
    assert again.status == "pending"


def test_GM移除必须写理由(api_client, signed_up):
    game, player, record = signed_up()
    api_client.force_authenticate(game.gm)
    url = f"/api/v1/games/{game.pk}/signups/{record.pk}/remove/"

    assert api_client.post(url, {}, format="json").status_code == 400
    response = api_client.post(url, {"reason": "反复鸽团"}, format="json")

    assert response.status_code == 200
    record.refresh_from_db()
    assert record.status == SIGNUP_REMOVED
    note = Notification.objects.filter(recipient=player, event=events.SIGNUP_RESULT).latest("id")
    assert note.payload["reason"] == "反复鸽团"


def test_非本团GM不能移除别人的报名(api_client, signed_up, gm_factory):
    game, player, record = signed_up()
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/remove/", {"reason": "手滑"}, format="json"
    )
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_game_gm"
    record.refresh_from_db()
    assert record.status != SIGNUP_REMOVED


# --------------------------------------------------------------------------
# 开始 / 结团
# --------------------------------------------------------------------------


def test_到点自动进入进行中(game_factory):
    game = game_factory()
    Game.objects.filter(pk=game.pk).update(start_at=ago(minutes=5), card_deadline=ago(minutes=5))
    game.refresh_from_db()

    services.refresh_game(game)
    game.refresh_from_db()
    assert game.status == GAME_RUNNING


def test_GM可以手动开始(api_client, game_factory):
    game = game_factory()
    api_client.force_authenticate(game.gm)
    response = api_client.post(f"/api/v1/games/{game.pk}/start/")
    assert response.status_code == 200
    game.refresh_from_db()
    assert game.status == GAME_RUNNING


def test_结团只给到场者计次数(api_client, game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(hours=1), max_players=3)
    came, absent = user_factory(), user_factory()
    came_signup = accept(game, came, card_factory)
    absent_signup = accept(game, absent, card_factory)

    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/finish/",
        {"attended_signup_ids": [came_signup.pk]},
        format="json",
    )

    assert response.status_code == 200
    game.refresh_from_db()
    assert game.status == GAME_FINISHED
    assert game.finished_at is not None

    came_signup.refresh_from_db()
    absent_signup.refresh_from_db()
    assert came_signup.attended is True
    assert absent_signup.attended is False

    assert ensure_player_card(came).games_played == 1
    assert ensure_player_card(absent).games_played == 0
    # 卡的参团记录也只跟着到场者
    came_signup.card.refresh_from_db()
    absent_signup.card.refresh_from_db()
    assert came_signup.card.play_count == 1
    assert absent_signup.card.play_count == 0
    # GM 的主持次数 +1
    assert recompute_gm_card(game.gm).games_hosted == 1
    # 结团发「评价开放」通知
    assert Notification.objects.filter(recipient=came, event=events.REVIEW_OPENED).count() == 1
    assert not Notification.objects.filter(recipient=absent, event=events.REVIEW_OPENED).exists()


def test_结团幂等重复调用不重复计数(game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(hours=1))
    player = user_factory()
    record = accept(game, player, card_factory)

    services.finish_game(game, attended_signup_ids=[record.pk])
    services.finish_game(game, attended_signup_ids=[record.pk])
    services.finish_game(game, attended_signup_ids=[record.pk])

    assert ensure_player_card(player).games_played == 1
    record.card.refresh_from_db()
    assert record.card.play_count == 1
    assert Notification.objects.filter(recipient=player, event=events.REVIEW_OPENED).count() == 1
    assert recompute_gm_card(game.gm).games_hosted == 1


def test_到场名单不能塞别的团的人(game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(hours=1))
    other = game_factory(start_at=soon(hours=1))
    stranger = accept(other, user_factory(), card_factory)

    with pytest.raises(services.InvalidSignupStatus):
        services.finish_game(game, attended_signup_ids=[stranger.pk])


def test_只有本团GM能结团(api_client, game_factory, gm_factory):
    game = game_factory()
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        f"/api/v1/games/{game.pk}/finish/", {"attended_signup_ids": []}, format="json"
    )
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_game_gm"


# --------------------------------------------------------------------------
# 取消
# --------------------------------------------------------------------------


def test_取消团必须写理由且不计任何次数(api_client, game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(hours=1))
    player = user_factory()
    record = accept(game, player, card_factory)

    api_client.force_authenticate(game.gm)
    assert api_client.post(f"/api/v1/games/{game.pk}/cancel/", {}, format="json").status_code == 400

    response = api_client.post(
        f"/api/v1/games/{game.pk}/cancel/", {"reason": "GM 住院了"}, format="json"
    )
    assert response.status_code == 200
    game.refresh_from_db()
    assert game.status == GAME_CANCELLED
    assert game.cancel_reason == "GM 住院了"

    # 取消团不计入任何次数
    assert services.player_games_played(player) == 0
    assert recompute_player_card(player).games_played == 0
    assert recompute_gm_card(game.gm).games_hosted == 0
    record.card.refresh_from_db()
    assert record.card.play_count == 0
    # 已交的卡仍留在 PL 的卡列表里
    assert record.card.owner_id == player.pk
    assert Notification.objects.filter(recipient=player, event=events.SIGNUP_RESULT).exists()


def test_已结团的团不能再取消(game_factory, user_factory, card_factory):
    # W5：结团必须至少有一位到场 PL（`no_attendee`）。
    game = game_factory(start_at=soon(hours=1))
    record = accept(game, user_factory(), card_factory)
    services.finish_game(game, attended_signup_ids=[record.pk])
    with pytest.raises(services.InvalidGameStatus):
        services.cancel_game(game, reason="反悔了")


def test_已取消的团不能结团(game_factory):
    game = game_factory()
    services.cancel_game(game, reason="人凑不齐")
    with pytest.raises(services.InvalidGameStatus):
        services.finish_game(game, attended_signup_ids=[])


def test_零到场不能结团(game_factory, user_factory, card_factory):
    """W5：到场名单为空一律 `no_attendee`。

    零人团既不产生任何计数，又能被 GM 用来刷评价的延迟锁（reviews 17.2），
    所以不给「结」出来；跑完发现一个人都没到的团只能由 GM 取消。
    """
    game = game_factory(start_at=soon(hours=1))
    accept(game, user_factory(), card_factory)  # 报名了但一个都没勾到场
    with pytest.raises(services.NoAttendee):
        services.finish_game(game, attended_signup_ids=[])
    game.refresh_from_db()
    assert game.status != GAME_FINISHED


# --------------------------------------------------------------------------
# 自动晋升 GM
# --------------------------------------------------------------------------


def test_参团三次自动晋升GM(game_factory, user_factory, card_factory, site_config):
    """阈值读站点配置（默认 3）；只有实际到场的结团才算。"""
    player = user_factory()
    assert site_config.gm_auto_promote_threshold == 3

    for index in range(3):
        game = game_factory(title=f"第 {index} 团", start_at=soon(hours=1))
        record = accept(game, player, card_factory)
        services.finish_game(game, attended_signup_ids=[record.pk])
        player.refresh_from_db()
        if index < 2:
            assert player.is_gm is False, "不到阈值不应该晋升"

    player = User.objects.get(pk=player.pk)
    assert player.is_gm is True
    assert Notification.objects.filter(recipient=player, event=events.GM_AUTO_PROMOTED).count() == 1


def test_没到场不算晋升次数(game_factory, user_factory, card_factory):
    """W5：到场名单不能为空，所以每个团另找一位真到场的人凑数。"""
    player = user_factory()
    for index in range(4):
        game = game_factory(title=f"没去的第 {index} 团", start_at=soon(hours=1), max_players=4)
        accept(game, player, card_factory)  # 报了名但没到场
        present = accept(game, user_factory(), card_factory)
        services.finish_game(game, attended_signup_ids=[present.pk])
    player.refresh_from_db()
    assert player.is_gm is False
    assert ensure_player_card(player).games_played == 0


# --------------------------------------------------------------------------
# 场次
# --------------------------------------------------------------------------


def test_场次CRUD只有本团GM能改(api_client, game_factory, user_factory):
    game = game_factory()
    api_client.force_authenticate(game.gm)
    created = api_client.post(
        f"/api/v1/games/{game.pk}/sessions/",
        {"index": 0, "label": "第 0 回", "held_at": timezone.now().isoformat()},
        format="json",
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    api_client.force_authenticate(user_factory())
    patched = api_client.patch(
        f"/api/v1/games/{game.pk}/sessions/{session_id}/", {"label": "乱改"}, format="json"
    )
    assert patched.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert patched.json()["error"]["code"] == "not_game_gm"

    # 场次列表游客可读
    api_client.force_authenticate(user=None)
    listed = api_client.get(f"/api/v1/games/{game.pk}/sessions/")
    assert listed.status_code == 200
    assert listed.json()["results"][0]["display_label"] == "第 0 回"


# --------------------------------------------------------------------------
# W5：改动报名状态后要重算相关用户的卡片
# --------------------------------------------------------------------------


def _stale(user, *, games_played: int):
    """人为把玩家卡的缓存字段写脏，模拟「名单变了、卡片还停在旧值」。"""
    card = ensure_player_card(user)
    card.games_played = games_played
    card.save(update_fields=["games_played"])
    return card


def test_GM移除报名者后重算该用户的卡片(game_factory, user_factory, card_factory):
    """`games_played` / 赞倒赞 / 被评次数全是按 DB 现状重算的缓存，
    而报名门槛读的就是这些缓存 —— 漏一处就会出现缓存与名单对不上的漂移。"""
    game = game_factory(start_at=soon(hours=1))
    player = user_factory()
    record = accept(game, player, card_factory)
    card = _stale(player, games_played=99)

    services.gm_remove(record, reason="捣乱")

    card.refresh_from_db()
    assert card.games_played == 0


def test_自己退出后重算卡片(game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(days=3))
    player = user_factory()
    record = accept(game, player, card_factory)
    card = _stale(player, games_played=77)

    services.withdraw(record, reason="临时有事")

    card.refresh_from_db()
    assert card.games_played == 0


def test_GM审批后重算卡片(game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(days=3), signup_mode=SIGNUP_POOL_REVIEW)
    player = user_factory()
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    record.refresh_from_db()
    card = _stale(player, games_played=55)

    services.review_signup(record, approved=True)

    card.refresh_from_db()
    assert card.games_played == 0


def test_取消团后重算全部受影响用户的卡片(game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(days=3))
    player = user_factory()
    accept(game, player, card_factory)
    player_card = _stale(player, games_played=42)
    gm_card = _stale(game.gm, games_played=43)

    services.cancel_game(game, reason="人凑不齐")

    player_card.refresh_from_db()
    gm_card.refresh_from_db()
    assert (player_card.games_played, gm_card.games_played) == (0, 0)
