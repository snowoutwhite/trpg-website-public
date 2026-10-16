"""招募列表的排序白名单、标签列表分页、团详情的评价窗口截止（W5 前端 W4b 提出）。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.games import services
from apps.games.models import Tag
from apps.games.tests.conftest import soon

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/games/"
TAGS_URL = "/api/v1/games/tags/"


def titles(response) -> list[str]:
    return [row["title"] for row in response.json()["results"]]


@pytest.fixture
def three_games(game_factory, gm_factory):
    """三个团：开团时间与创建顺序**故意相反**，这样两种排序结果不会碰巧相同。"""
    gm = gm_factory()
    late = game_factory(gm, title="最晚开团", start_at=soon(days=30))
    middle = game_factory(gm, title="中间开团", start_at=soon(days=20))
    early = game_factory(gm, title="最早开团", start_at=soon(days=10))
    return early, middle, late


# --------------------------------------------------------------------------
# ① ?ordering= 白名单
# --------------------------------------------------------------------------


def test_默认按发布时间倒序(api_client, three_games):
    assert titles(api_client.get(LIST_URL)) == ["最早开团", "中间开团", "最晚开团"]


@pytest.mark.parametrize(
    ("ordering", "expected"),
    [
        ("start_at", ["最早开团", "中间开团", "最晚开团"]),
        ("-start_at", ["最晚开团", "中间开团", "最早开团"]),
        ("-created_at", ["最早开团", "中间开团", "最晚开团"]),
    ],
)
def test_白名单内的排序生效(api_client, three_games, ordering, expected):
    assert titles(api_client.get(f"{LIST_URL}?ordering={ordering}")) == expected


@pytest.mark.parametrize(
    "ordering",
    [
        "gm__email",  # 二分别人的邮箱
        "gm__nickname",
        "signups__id",  # 推报名先后
        "-id",
        "title",
        "?",  # 随机排序：既拖库又能被反复采样
        "start_at,gm__email",
        "gm__email; DROP TABLE",
    ],
)
def test_白名单外的排序一律回落到默认且不报错(api_client, three_games, ordering):
    """排序参数是一条**信道**：放开任意字段就能按隐私字段二分出它的值。

    认不出的值静默回落到默认顺序，既不给信道，也不因为老前端传了别的值就 400。
    """
    response = api_client.get(f"{LIST_URL}?ordering={ordering}")
    assert response.status_code == 200
    assert titles(response) == ["最早开团", "中间开团", "最晚开团"]


def test_排序与筛选分页同时生效(api_client, three_games):
    page = api_client.get(f"{LIST_URL}?ordering=-start_at&page_size=2").json()
    assert page["count"] == 3
    assert [row["title"] for row in page["results"]] == ["最晚开团", "中间开团"]


# --------------------------------------------------------------------------
# ② 标签列表：分页 + ?q=
# --------------------------------------------------------------------------


def test_标签列表分页而不是硬截断到50(api_client, game_factory):
    """原来是 `queryset[:50]`，第 51 个标签之后谁也翻不到。"""
    game_factory(tags=[f"标签{index:03d}" for index in range(60)])
    total = Tag.objects.count()  # 60 个自建 + 2 个预设

    first = api_client.get(f"{TAGS_URL}?page_size=50").json()
    assert first["count"] == total
    assert len(first["results"]) == 50
    assert first["next"] is not None

    second = api_client.get(f"{TAGS_URL}?page_size=50&page=2").json()
    assert len(second["results"]) == total - 50
    # 两页不重不漏
    names = {row["name"] for row in first["results"]} | {row["name"] for row in second["results"]}
    assert len(names) == total


def test_标签搜索仍然是服务端过滤(api_client, game_factory):
    game_factory(tags=["克苏鲁的呼唤", "克苏鲁神话", "都市传说"])
    results = api_client.get(f"{TAGS_URL}?q=克苏鲁").json()
    assert results["count"] == 2
    assert {row["name"] for row in results["results"]} == {"克苏鲁的呼唤", "克苏鲁神话"}


def test_标签预设排在前面(api_client, game_factory):
    game_factory(tags=["自建标签"])
    results = api_client.get(TAGS_URL).json()["results"]
    assert results[0]["is_preset"] is True


# --------------------------------------------------------------------------
# ③ 团详情的 review_window_ends_at
# --------------------------------------------------------------------------


def test_未结团时评价窗口截止为空(api_client, game_factory):
    game = game_factory()
    body = api_client.get(f"{LIST_URL}{game.pk}/").json()
    assert body["review_window_ends_at"] is None


def test_结团后评价窗口截止等于结团时间加站点配置天数(
    api_client, game_factory, user_factory, card_factory, site_config
):
    from django.utils import timezone

    game = game_factory(start_at=soon(hours=1))
    record = services.signup(game, user_factory())
    services.submit_card(record, card_factory(record.player))
    record.refresh_from_db()
    services.finish_game(game, attended_signup_ids=[record.pk])
    game.refresh_from_db()

    body = api_client.get(f"{LIST_URL}{game.pk}/").json()

    expected = game.finished_at + timedelta(days=site_config.review_window_days)
    assert body["review_window_ends_at"] is not None
    parsed = timezone.datetime.fromisoformat(body["review_window_ends_at"])
    assert abs((parsed - expected).total_seconds()) < 1


def test_评价窗口截止随站点配置变化(
    api_client, game_factory, user_factory, card_factory, site_config
):
    """天数是站级可配项，前端不该自己拿 finished_at 再算一遍。"""
    game = game_factory(start_at=soon(hours=1))
    record = services.signup(game, user_factory())
    services.submit_card(record, card_factory(record.player))
    record.refresh_from_db()
    services.finish_game(game, attended_signup_ids=[record.pk])

    before = api_client.get(f"{LIST_URL}{game.pk}/").json()["review_window_ends_at"]
    site_config.review_window_days = site_config.review_window_days + 10
    site_config.save()
    after = api_client.get(f"{LIST_URL}{game.pk}/").json()["review_window_ends_at"]

    assert after > before


# --------------------------------------------------------------------------
# ④ ?mode= 开团方式筛选（前端招募页的「线上 / 线下」筹码走服务端，不再本页过滤）
# --------------------------------------------------------------------------


@pytest.fixture
def two_modes(game_factory, gm_factory):
    from apps.games.models import MODE_OFFLINE, MODE_ONLINE

    gm = gm_factory()
    game_factory(gm, title="线上团", mode=MODE_ONLINE)
    game_factory(gm, title="线下团", mode=MODE_OFFLINE, location="某桌游店")


@pytest.mark.parametrize(("mode", "expected"), [("online", ["线上团"]), ("offline", ["线下团"])])
def test_mode筛选命中(api_client, two_modes, mode, expected):
    response = api_client.get(f"{LIST_URL}?mode={mode}")
    assert response.status_code == 200
    assert titles(response) == expected


@pytest.mark.parametrize("mode", ["ONLINE", "hybrid", "__other__", "online,offline", "' OR 1=1"])
def test_mode非法值静默忽略(api_client, two_modes, mode):
    """认不出的值当没传：不 400、不筛，与 `?ordering=` 同口径。"""
    response = api_client.get(f"{LIST_URL}?mode={mode}")
    assert response.status_code == 200
    assert sorted(titles(response)) == ["线上团", "线下团"]


def test_mode与翻页计数一致(api_client, two_modes):
    """筛选在分页之前做：count 是筛后的总数，不是本页条数。"""
    page = api_client.get(f"{LIST_URL}?mode=offline&page_size=1").json()
    assert page["count"] == 1
    assert page["next"] is None
