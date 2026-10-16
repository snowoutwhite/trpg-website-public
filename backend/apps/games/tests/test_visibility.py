"""名单可见性三层 + 隐私字段不泄露。"""

from __future__ import annotations

import pytest

from apps.games import services
from apps.games.models import Game

pytestmark = pytest.mark.django_db


def detail_url(game: Game) -> str:
    return f"/api/v1/games/{game.pk}/"


def recruiting_url(game: Game) -> str:
    return f"/api/v1/games/{game.pk}/signups/"


def roster_url(game: Game) -> str:
    return f"/api/v1/games/{game.pk}/roster/"


@pytest.fixture
def team(game_factory, user_factory, card_factory):
    """一个团：1 个已成功报团的 PL（accepted）+ 1 个还没交卡的 PL（pending）。"""
    game = game_factory()
    member = user_factory(nickname="已过卡的人", email="member@example.com")
    waiting = user_factory(nickname="还没交卡的人", email="waiting@example.com")

    accepted = services.signup(game, member)
    services.submit_card(accepted, card_factory(member))
    pending = services.signup(game, waiting)
    return {"game": game, "member": member, "waiting": waiting, "accepted": accepted, "pending": pending}


# --------------------------------------------------------------------------
# 第一层：游客
# --------------------------------------------------------------------------


def test_游客能看团公告(api_client, team):
    response = api_client.get(detail_url(team["game"]))
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == team["game"].title
    assert body["gm"]["nickname"] == team["game"].gm.nickname
    assert body["my_signup"] is None


def test_游客看不到任何报名者身份(api_client, team):
    raw = api_client.get(detail_url(team["game"])).content.decode()
    assert "已过卡的人" not in raw
    assert "还没交卡的人" not in raw


def test_游客拿不到两份名单(api_client, team):
    for url in (recruiting_url(team["game"]), roster_url(team["game"])):
        response = api_client.get(url)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"


def test_团列表游客可读且不含邮箱(api_client, team):
    response = api_client.get("/api/v1/games/")
    assert response.status_code == 200
    raw = response.content.decode()
    assert team["game"].title in raw
    assert "@example.com" not in raw


# --------------------------------------------------------------------------
# 第二层：登录但非同团
# --------------------------------------------------------------------------


def test_登录用户能看招募中名单含报名顺序(api_client, team, user_factory):
    api_client.force_authenticate(user_factory())
    response = api_client.get(recruiting_url(team["game"]))

    assert response.status_code == 200
    body = response.json()
    rows = body["results"]
    # 招募中名单 = 未定下来的报名（待交卡 / 待审），不含已通过的人
    assert [row["player"]["nickname"] for row in rows] == ["还没交卡的人"]
    assert rows[0]["order"] == 2
    assert set(rows[0]["player"]) == {"id", "nickname", "avatar", "is_gm"}
    assert body["accepted_count"] == 1  # 只给数量，不给身份


def test_登录非同团看不到正式名单(api_client, team, user_factory):
    api_client.force_authenticate(user_factory())
    response = api_client.get(roster_url(team["game"]))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_招募中名单不泄露邮箱(api_client, team, user_factory):
    api_client.force_authenticate(user_factory())
    raw = api_client.get(recruiting_url(team["game"])).content.decode()
    assert "@example.com" not in raw


# --------------------------------------------------------------------------
# 第三层：同团
# --------------------------------------------------------------------------


def test_同团成员能看正式名单(api_client, team):
    api_client.force_authenticate(team["member"])
    response = api_client.get(roster_url(team["game"]))

    assert response.status_code == 200
    body = response.json()
    assert body["is_gm"] is False
    assert [row["player"]["nickname"] for row in body["results"]] == ["已过卡的人"]
    # 同团的 PL 看不到别人的卡与审批备注
    assert "card" not in body["results"][0]
    assert "review_note" not in body["results"][0]


def test_GM能看全量名单与卡(api_client, team):
    api_client.force_authenticate(team["game"].gm)
    response = api_client.get(roster_url(team["game"]))

    assert response.status_code == 200
    body = response.json()
    assert body["is_gm"] is True
    assert len(body["results"]) == 2
    with_card = [row for row in body["results"] if row["card"]][0]
    assert with_card["card"]["download_url"].endswith("/download/")
    assert "protected/" not in response.content.decode()  # 绝不回传存储路径


def test_被移出的人不再算同团(api_client, team):
    services.gm_remove(team["accepted"], reason="缺席太多")
    api_client.force_authenticate(team["member"])
    assert api_client.get(roster_url(team["game"])).status_code == 403


def test_我的报名只返回自己的(api_client, team):
    api_client.force_authenticate(team["member"])
    response = api_client.get("/api/v1/games/my-signups/")

    assert response.status_code == 200
    rows = response.json()["results"]
    assert len(rows) == 1
    assert rows[0]["id"] == team["accepted"].pk
    assert "还没交卡的人" not in response.content.decode()
