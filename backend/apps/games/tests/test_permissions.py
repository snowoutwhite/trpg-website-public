"""权限拒绝路径：游客写操作、非本团 GM、越权交卡、CSRF。"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.games import services
from apps.games.models import Game, Signup

from .conftest import soon

pytestmark = pytest.mark.django_db


def test_游客不能放团(api_client):
    response = api_client.post(
        "/api/v1/games/", {"title": "游客团", "start_at": soon(days=3).isoformat()}, format="json"
    )
    assert response.status_code in (401, 403)
    assert not Game.objects.filter(title="游客团").exists()


@pytest.mark.parametrize(
    "path,payload",
    [
        ("signup/", {}),
        ("withdraw/", {}),
        ("submit-card/", {"card_id": 1}),
        ("start/", {}),
        ("cancel/", {"reason": "随便"}),
        ("finish/", {"attended_signup_ids": []}),
        ("expand/", {"max_players": 9}),
    ],
)
def test_游客不能做任何写操作(api_client, game_factory, path, payload):
    game = game_factory()
    response = api_client.post(f"/api/v1/games/{game.pk}/{path}", payload, format="json")
    assert response.status_code in (401, 403)
    game.refresh_from_db()
    assert game.status == "recruiting"
    assert game.signups.count() == 0


@pytest.mark.parametrize("path", ["start/", "expand/", "cancel/", "finish/"])
def test_别的GM不能操作我的团(api_client, game_factory, gm_factory, path):
    game = game_factory()
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        f"/api/v1/games/{game.pk}/{path}",
        {"reason": "手滑", "max_players": 99, "attended_signup_ids": []},
        format="json",
    )
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_game_gm"
    game.refresh_from_db()
    assert game.status == "recruiting"
    assert game.max_players == 5


def test_别人不能改我的团公告(api_client, game_factory, gm_factory):
    game = game_factory()
    api_client.force_authenticate(gm_factory())
    response = api_client.patch(f"/api/v1/games/{game.pk}/", {"title": "被篡改"}, format="json")

    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_game_gm"
    game.refresh_from_db()
    assert game.title != "被篡改"


def test_改公告不能顺手改状态(api_client, game_factory):
    """`status` 不在可写字段里，状态只能走动作接口。"""
    game = game_factory()
    api_client.force_authenticate(game.gm)
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/", {"status": "finished", "title": "改个名"}, format="json"
    )
    assert response.status_code == 200
    game.refresh_from_db()
    assert game.status == "recruiting"
    assert game.title == "改个名"


def test_没报名的人不能交卡(api_client, game_factory, user_factory, card_factory):
    game = game_factory()
    outsider = user_factory()
    api_client.force_authenticate(outsider)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/submit-card/", {"card_id": card_factory(outsider).pk}, format="json"
    )
    assert response.status_code == 404


def test_不能替别人退出(api_client, signed_up, user_factory):
    game, player, record = signed_up()
    api_client.force_authenticate(user_factory())
    response = api_client.post(f"/api/v1/games/{game.pk}/withdraw/", {}, format="json")
    assert response.status_code == 404
    record.refresh_from_db()
    assert record.status == "pending"


def test_GM不能审批别的团的报名(api_client, signed_up, game_factory):
    game, player, record = signed_up()
    other = game_factory()  # 另一个团，GM 不同
    api_client.force_authenticate(other.gm)
    response = api_client.post(
        f"/api/v1/games/{other.pk}/signups/{record.pk}/review/", {"approved": True}, format="json"
    )
    assert response.status_code == 404  # 报名不属于此团
    record.refresh_from_db()
    assert record.status == "pending"


@pytest.mark.parametrize("path", ["signup/", "withdraw/"])
def test_写接口缺少csrf_token时被拒(db, signed_up, path):
    game, player, record = signed_up()
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(email=player.email, password="testpass1234")

    response = client.post(f"/api/v1/games/{game.pk}/{path}", {}, format="json")
    assert response.status_code == 403
    record.refresh_from_db()
    assert record.status == "pending"


def test_封禁用户不能报名(api_client, game_factory, user_factory):
    game = game_factory()
    player = user_factory()
    player.is_banned = True
    player.is_active = False
    player.save(update_fields=["is_banned", "is_active"])

    api_client.force_authenticate(player)
    assert api_client.post(f"/api/v1/games/{game.pk}/signup/").status_code == 403
    assert Signup.objects.count() == 0


def test_禁言的GM仍能审批与结团(api_client, signed_up, card_factory):
    """禁言只禁放团/报名/评价，团内管理照常。"""
    game, player, record = signed_up(signup_mode="pool_review", start_at=soon(hours=1))
    services.submit_card(record, card_factory(player))
    game.gm.is_muted = True
    game.gm.save(update_fields=["is_muted"])

    api_client.force_authenticate(game.gm)
    approved = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/review/", {"approved": True}, format="json"
    )
    assert approved.status_code == 200
    finished = api_client.post(
        f"/api/v1/games/{game.pk}/finish/", {"attended_signup_ids": [record.pk]}, format="json"
    )
    assert finished.status_code == 200
