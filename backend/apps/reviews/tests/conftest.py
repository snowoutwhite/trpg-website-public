"""团后评价测试的共用夹具。

造团一律直接写 ORM，不走 games 的报名/交卡流程：本 app 只关心「谁实际到场了、
团什么时候结的」，报名状态机是 games 自己的测试负责的事。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.games.models import GAME_FINISHED, SIGNUP_ACCEPTED, Game, Signup

REVIEWS_URL = "/api/v1/reviews/"
PENDING_URL = "/api/v1/reviews/pending/"
QUOTA_URL = "/api/v1/reviews/quota/"
GIVEN_URL = "/api/v1/reviews/mine/given/"
RECEIVED_URL = "/api/v1/reviews/mine/received/"


def mutual_url(game) -> str:
    return f"/api/v1/reviews/games/{game.pk}/mutual/"


def ago(**kwargs):
    return timezone.now() - timedelta(**kwargs)


@pytest.fixture
def gm_factory(db, user_factory):
    """造一个 GM 身份的用户（signals 会顺带建 GM 卡）。"""

    def make(**kwargs):
        user = user_factory(**kwargs)
        user.is_gm = True
        user.save(update_fields=["is_gm"])
        return user

    return make


@pytest.fixture
def game_factory(db):
    """造团：默认「刚刚结团、所有报名者都到场、免交卡、互见关闭」。"""
    counter = {"n": 0}

    def make(
        gm,
        players=(),
        *,
        attended=None,
        finished_at=None,
        status=GAME_FINISHED,
        mutual_review=False,
        title=None,
    ):
        counter["n"] += 1
        finished = finished_at or timezone.now()
        start_at = finished - timedelta(hours=3)
        game = Game.objects.create(
            gm=gm,
            title=title or f"第 {counter['n']} 个团",
            start_at=start_at,
            card_deadline=start_at,
            requires_card=False,
            mutual_review=mutual_review,
            max_players=max(len(players), 1),
            status=status,
            finished_at=finished if status == GAME_FINISHED else None,
        )
        attended_ids = {user.pk for user in (players if attended is None else attended)}
        for index, player in enumerate(players, start=1):
            Signup.objects.create(
                game=game,
                player=player,
                order=index,
                status=SIGNUP_ACCEPTED,
                attended=player.pk in attended_ids,
            )
        return game

    return make


@pytest.fixture
def pass_delay(db, gm_factory, game_factory):
    """让 `user` 跨过延迟可见门槛：在 `after` 之后再结 `count` 个团。"""

    def make(user, after, *, count: int = 3):
        gm = gm_factory()
        return [
            game_factory(gm, [user], finished_at=after + timedelta(hours=index))
            for index in range(1, count + 1)
        ]

    return make


@pytest.fixture
def submit(api_client):
    """以 `reviewer` 的身份提交一条评价。"""

    def post(reviewer, game, reviewee, *, verdict="like", text="配合得很好"):
        api_client.force_authenticate(reviewer)
        response = api_client.post(
            REVIEWS_URL,
            {"game": game.pk, "reviewee": reviewee.pk, "verdict": verdict, "text": text},
            format="json",
        )
        api_client.force_authenticate(None)
        return response

    return post
