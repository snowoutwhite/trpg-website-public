"""评价规则：谁能评谁、什么时候能评、必填文字、upsert、配额。"""

from __future__ import annotations

import pytest

from apps.games.models import GAME_RUNNING
from apps.reviews.models import Review
from apps.reviews.tests.conftest import PENDING_URL, QUOTA_URL, RECEIVED_URL, REVIEWS_URL, ago

pytestmark = pytest.mark.django_db


def code(response) -> str:
    return response.json()["error"]["code"]


def test_非到场者不能评价(user_factory, gm_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    outsider = user_factory()
    game = game_factory(gm, [player])

    response = submit(outsider, game, player)

    assert response.status_code == 403
    assert code(response) == "not_attendee"


def test_报名了但没到场的人既不能评也不能被评(user_factory, gm_factory, game_factory, submit):
    gm = gm_factory()
    present = user_factory()
    absent = user_factory()
    game = game_factory(gm, [present, absent], attended=[present])

    assert code(submit(absent, game, present)) == "not_attendee"
    assert code(submit(present, game, absent)) == "invalid_review_target"


def test_不能评价自己(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])

    response = submit(player, game, player)

    assert response.status_code == 403
    assert code(response) == "cannot_review_self"


def test_未结团不能评价(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player], status=GAME_RUNNING)

    response = submit(player, game, gm)

    # W5 状态码统一：「团还没结团」是目标状态不对 → 400（与 games 的 invalid_game_status 同档）
    assert response.status_code == 400
    assert code(response) == "review_not_open"


def test_窗口关闭后冻结(gm_factory, user_factory, game_factory, submit, site_config):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player], finished_at=ago(days=site_config.review_window_days + 1))

    response = submit(player, game, gm)

    # W5 状态码统一：时间窗关闭 → 400（与 games 的 card_deadline_passed、
    # gallery 的 gallery_window_closed 同档）
    assert response.status_code == 400
    assert code(response) == "review_window_closed"


def test_窗口内可改档与文字_且不产生第二行(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])

    first = submit(player, game, gm, verdict="like", text="很会带团")
    second = submit(player, game, gm, verdict="dislike", text="改主意了")

    assert first.status_code == 201
    assert second.status_code == 200
    assert Review.objects.filter(game=game, reviewer=player, reviewee=gm).count() == 1
    review = Review.objects.get(game=game, reviewer=player, reviewee=gm)
    assert review.verdict == "dislike"
    assert review.text == "改主意了"


def test_赞和倒赞都必须附文字(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])

    blank = submit(player, game, gm, text="   ")

    assert blank.status_code == 400
    assert code(blank) == "validation_error"
    assert not Review.objects.exists()


def test_关闭赞功能时入口403且列表隐藏(
    gm_factory, user_factory, game_factory, submit, api_client, site_config
):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    assert submit(player, game, gm).status_code == 201

    site_config.like_feature_enabled = False
    site_config.save()

    denied = submit(player, game, gm, verdict="dislike", text="再评一次")
    assert denied.status_code == 403
    assert code(denied) == "like_feature_disabled"

    api_client.force_authenticate(player)
    assert api_client.get(PENDING_URL).status_code == 403
    api_client.force_authenticate(gm)
    assert api_client.get(RECEIVED_URL).json()["results"] == []

    # 数据只是隐藏，不删。
    assert Review.objects.count() == 1


def test_禁言者不能评价(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    player.is_muted = True
    player.save(update_fields=["is_muted"])
    game = game_factory(gm, [player])

    assert submit(player, game, gm).status_code == 403


def test_评价对象范围_PL评GM与其他到场PL_GM评所有到场PL(
    gm_factory, user_factory, game_factory, api_client
):
    gm = gm_factory()
    first, second = user_factory(), user_factory()
    game_factory(gm, [first, second])

    api_client.force_authenticate(first)
    targets = api_client.get(PENDING_URL).json()["results"][0]["targets"]
    assert {(item["user"]["id"], item["role"]) for item in targets} == {
        (gm.pk, "gm"),
        (second.pk, "pl"),
    }

    api_client.force_authenticate(gm)
    gm_targets = api_client.get(PENDING_URL).json()["results"][0]["targets"]
    assert {(item["user"]["id"], item["role"]) for item in gm_targets} == {
        (first.pk, "pl"),
        (second.pk, "pl"),
    }


def test_待评列表剔除已评过的人(gm_factory, user_factory, game_factory, api_client, submit):
    gm = gm_factory()
    first, second = user_factory(), user_factory()
    game = game_factory(gm, [first, second])
    submit(first, game, gm)

    api_client.force_authenticate(first)
    targets = api_client.get(PENDING_URL).json()["results"][0]["targets"]

    assert [item["user"]["id"] for item in targets] == [second.pk]


def test_待评列表不含窗口已关闭的团(
    gm_factory, user_factory, game_factory, api_client, site_config
):
    gm = gm_factory()
    player = user_factory()
    game_factory(gm, [player], finished_at=ago(days=site_config.review_window_days + 1))

    api_client.force_authenticate(player)
    assert api_client.get(PENDING_URL).json()["results"] == []


def test_配额等于各团人数减一之和(gm_factory, user_factory, game_factory, api_client, submit):
    gm = gm_factory()
    first, second = user_factory(), user_factory()
    # 团一：GM + 2 PL（3 人）；团二：GM + 1 PL（2 人）
    game_one = game_factory(gm, [first, second])
    game_factory(gm, [first])
    submit(first, game_one, gm)

    api_client.force_authenticate(first)
    quota = api_client.get(QUOTA_URL).json()

    assert quota["quota"] == 3  # (3-1) + (2-1)
    assert quota["used"] == 1
    assert quota["remaining"] == 2


def test_未登录一律拒绝(api_client, gm_factory, user_factory, game_factory):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])

    assert api_client.get(PENDING_URL).status_code in (401, 403)
    assert api_client.get(RECEIVED_URL).status_code in (401, 403)
    assert (
        api_client.post(
            REVIEWS_URL,
            {"game": game.pk, "reviewee": gm.pk, "verdict": "like", "text": "好"},
            format="json",
        ).status_code
        in (401, 403)
    )
