"""时间锁与互见：延迟 3 团才可见、互见开关、互见同样匿名同样延迟。"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from apps.games.models import GAME_RUNNING
from apps.reviews.tests.conftest import RECEIVED_URL, mutual_url

pytestmark = pytest.mark.django_db


def code(response) -> str:
    return response.json()["error"]["code"]


def test_延迟可见边界_恰好2团不可见3团可见(
    user_factory, gm_factory, game_factory, submit, api_client, pass_delay
):
    gm = gm_factory()
    reviewee = user_factory()
    game = game_factory(gm, [reviewee], title="被评的那个团")
    submit(gm, game, reviewee, text="延迟测试")

    api_client.force_authenticate(reviewee)

    # 0 个后续团：不可见，只给计数
    payload = api_client.get(RECEIVED_URL).json()
    assert payload["results"] == []
    assert payload["hidden_count"] == 1
    assert payload["visible_after_games"] == 3

    # 2 个后续团：仍不可见
    pass_delay(reviewee, game.finished_at, count=2)
    payload = api_client.get(RECEIVED_URL).json()
    assert payload["results"] == []
    assert payload["hidden_count"] == 1

    # 第 3 个后续团结团后才可见
    game_factory(gm_factory(), [reviewee], finished_at=game.finished_at + timedelta(hours=9))
    payload = api_client.get(RECEIVED_URL).json()
    assert [item["text"] for item in payload["results"]] == ["延迟测试"]
    assert payload["hidden_count"] == 0


def test_延迟计数含作为GM结团的团(user_factory, gm_factory, game_factory, submit, api_client):
    """「作为 PL 或 GM attended 都计」。"""
    host = gm_factory()
    reviewee = gm_factory()
    game = game_factory(host, [reviewee])
    submit(host, game, reviewee, text="GM 也算")

    # 团里必须真的有到场 PL：零人团不计入延迟（W3 红队修复，见 services.finished_games_after）。
    guest = user_factory()
    for index in range(1, 4):
        game_factory(reviewee, [guest], finished_at=game.finished_at + timedelta(hours=index))

    api_client.force_authenticate(reviewee)
    assert len(api_client.get(RECEIVED_URL).json()["results"]) == 1


def test_之前结团的团不算进延迟(user_factory, gm_factory, game_factory, submit, api_client):
    gm = gm_factory()
    reviewee = user_factory()
    for _ in range(3):
        game_factory(gm, [reviewee])  # 都结在被评那个团之前
    game = game_factory(gm, [reviewee], title="最后结的团")
    submit(gm, game, reviewee)

    api_client.force_authenticate(reviewee)
    payload = api_client.get(RECEIVED_URL).json()

    assert payload["results"] == []
    assert payload["hidden_count"] == 1


def test_互见关闭时403(user_factory, gm_factory, game_factory, submit, api_client):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player], mutual_review=False)
    submit(gm, game, player)

    api_client.force_authenticate(player)
    response = api_client.get(mutual_url(game))

    assert response.status_code == 403
    assert code(response) == "mutual_review_disabled"


def test_互见对非到场者403(user_factory, gm_factory, game_factory, api_client):
    gm = gm_factory()
    player = user_factory()
    outsider = user_factory()
    game = game_factory(gm, [player], mutual_review=True)

    api_client.force_authenticate(outsider)
    response = api_client.get(mutual_url(game))

    assert response.status_code == 403
    assert code(response) == "not_attendee"


def test_互见未结团403(user_factory, gm_factory, game_factory, api_client):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player], mutual_review=True, status=GAME_RUNNING)

    api_client.force_authenticate(player)
    assert code(api_client.get(mutual_url(game))) == "review_not_open"


def test_互见同样受延迟约束且同样匿名(
    user_factory, gm_factory, game_factory, submit, api_client, pass_delay
):
    gm = gm_factory(nickname="互见团的GM")
    first = user_factory(nickname="甲")
    second = user_factory(nickname="乙")
    game = game_factory(gm, [first, second], mutual_review=True, title="互见团")
    submit(gm, game, first, text="给甲的")
    submit(second, game, first, text="乙给甲的")
    submit(gm, game, second, text="给乙的")

    api_client.force_authenticate(first)
    early = api_client.get(mutual_url(game)).json()
    assert early["available"] is False
    assert early["groups"] == []

    pass_delay(first, game.finished_at)
    payload = api_client.get(mutual_url(game)).json()

    assert payload["available"] is True
    by_user = {group["user"]["nickname"]: group for group in payload["groups"]}
    assert set(by_user) == {"互见团的GM", "甲", "乙"}
    assert sorted(item["text"] for item in by_user["甲"]["reviews"]) == ["乙给甲的", "给甲的"]
    assert [item["text"] for item in by_user["乙"]["reviews"]] == ["给乙的"]
    # 互见面板同样不带评价人
    for entry in [item for group in payload["groups"] for item in group["reviews"]]:
        assert set(entry) == {"verdict", "verdict_display", "text", "reviewee_role", "game"}
    raw = json.dumps(payload, ensure_ascii=False)
    assert "reviewer" not in raw


def test_互见不让查看者提前读到自己收到的评价(
    user_factory, gm_factory, game_factory, submit, api_client, pass_delay
):
    """互见按**查看者**的延迟判定，否则互见面板就成了绕过时间锁的后门。"""
    gm = gm_factory()
    first = user_factory()
    second = user_factory()
    game = game_factory(gm, [first, second], mutual_review=True)
    submit(gm, game, first, text="给甲的")

    # 乙已经跨过延迟，甲还没有：甲自己看互见面板仍然是关着的
    pass_delay(second, game.finished_at)

    api_client.force_authenticate(first)
    assert api_client.get(mutual_url(game)).json()["available"] is False
    api_client.force_authenticate(second)
    assert api_client.get(mutual_url(game)).json()["available"] is True
