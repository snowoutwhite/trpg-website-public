"""业务规则与安全约束。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.games.models import GAME_CANCELLED, SIGNUP_REMOVED, Signup
from apps.profiles import levels
from apps.profiles.models import GMCard, PlayerCard
from apps.reviews import services
from apps.reviews.models import ROLE_GM, ROLE_PL, Review

pytestmark = pytest.mark.django_db


def _closed_at(site_config, *, extra_days=1):
    """一个「评价窗口已经关闭」的结团时刻。"""
    return timezone.now() - timedelta(days=site_config.review_window_days + extra_days)


def _review(game, reviewer, reviewee, verdict="like"):
    """直接落库（窗口已关，走 upsert 会被拒）。"""
    role = services.role_of(reviewee, game)
    return Review.objects.create(
        game=game, reviewer=reviewer, reviewee=reviewee, verdict=verdict, text="x", reviewee_role=role
    )


@pytest.fixture
def closed_game(site_config, gm_factory, user_factory, game_factory, pass_delay):
    """GM + 目标 PL + 两位同团 PL，窗口已关、目标已过延迟锁；目标只收到一个赞。"""
    gm = gm_factory()
    target, p1, p2 = user_factory(), user_factory(), user_factory()
    game = game_factory(gm, [target, p1, p2], finished_at=_closed_at(site_config))
    _review(game, p1, target, "like")
    pass_delay(target, game.finished_at)
    return {"gm": gm, "target": target, "p1": p1, "p2": p2, "game": game}


# --------------------------------------------------------------------------
# review_counts：无评价的计算
# --------------------------------------------------------------------------


def test_窗口已关且过了延迟锁_没评的到场成员计为无评价(closed_game):
    counts = services.review_counts(closed_game["target"], ROLE_PL)
    # 应评人 = GM + p1 + p2 = 3；p1 赞，GM 与 p2 没评 → 无评价 2
    assert counts == {"reviews_received": 3, "likes": 1, "dislikes": 0}


def test_窗口未关时没评的仍是待评价_不计无评价(
    site_config, gm_factory, user_factory, game_factory, pass_delay
):
    gm = gm_factory()
    target, p1 = user_factory(), user_factory()
    game = game_factory(gm, [target, p1], finished_at=timezone.now() - timedelta(days=1))
    _review(game, p1, target, "like")
    pass_delay(target, game.finished_at)
    assert services.review_counts(target, ROLE_PL) == {"reviews_received": 1, "likes": 1, "dislikes": 0}


def test_延迟锁未解时窗口关了也不计无评价(site_config, gm_factory, user_factory, game_factory):
    gm = gm_factory()
    target, p1 = user_factory(), user_factory()
    game_factory(gm, [target, p1], finished_at=_closed_at(site_config))
    assert services.review_counts(target, ROLE_PL) == {"reviews_received": 0, "likes": 0, "dislikes": 0}


def test_GM侧与玩家侧分开计无评价(closed_game, pass_delay):
    gm = closed_game["gm"]
    pass_delay(gm, closed_game["game"].finished_at)
    _review(closed_game["game"], closed_game["p2"], gm, "dislike")
    # GM 的应评人 = 三位到场 PL；p2 倒赞，其余两人无评价
    assert services.review_counts(gm, ROLE_GM) == {"reviews_received": 3, "likes": 0, "dislikes": 1}
    # GM 在这个团里不是 PL，玩家侧不受影响（pass_delay 的三个团窗口都没关）
    assert services.review_counts(gm, ROLE_PL) == {"reviews_received": 0, "likes": 0, "dislikes": 0}


def test_到场名单以正式到场为准(site_config, gm_factory, user_factory, game_factory, pass_delay):
    """没到场的、被移出的都不算应评人；目标自己没到场则整团不算。"""
    gm = gm_factory()
    target, came, absent, removed = (user_factory() for _ in range(4))
    game = game_factory(gm, [target, came, absent], attended=[target, came], finished_at=_closed_at(site_config))
    Signup.objects.create(game=game, player=removed, order=9, status=SIGNUP_REMOVED, attended=True)
    pass_delay(target, game.finished_at)
    # 应评人 = GM + came = 2，都没评
    assert services.review_counts(target, ROLE_PL)["reviews_received"] == 2

    # 目标本人没到场的团：他不是被评对象
    other = user_factory()
    game2 = game_factory(gm, [other, came], attended=[came], finished_at=_closed_at(site_config))
    pass_delay(other, game2.finished_at)
    assert services.review_counts(other, ROLE_PL)["reviews_received"] == 0


def test_取消的团不计(site_config, gm_factory, user_factory, game_factory, pass_delay):
    gm = gm_factory()
    target, p1 = user_factory(), user_factory()
    game = game_factory(gm, [target, p1], status=GAME_CANCELLED)
    pass_delay(target, _closed_at(site_config, extra_days=5))
    assert game.finished_at is None
    assert services.review_counts(target, ROLE_PL)["reviews_received"] == 0


def test_已评过的人不重复计无评价_评价人后来不在名单也不会算出负数(closed_game):
    target = closed_game["target"]
    game = closed_game["game"]
    _review(game, closed_game["gm"], target, "dislike")
    _review(game, closed_game["p2"], target, "like")
    assert services.review_counts(target, ROLE_PL) == {"reviews_received": 3, "likes": 2, "dislikes": 1}
    # p1 事后被从到场名单剔除（生产路径不会发生，防御性）：他的赞仍计入，无评价不会变负
    Signup.objects.filter(game=game, player=closed_game["p1"]).update(attended=False)
    counts = services.review_counts(target, ROLE_PL)
    assert counts["likes"] == 2 and counts["reviews_received"] >= counts["likes"] + counts["dislikes"]


# --------------------------------------------------------------------------
# 档位：无评价把档位往中性拉
# --------------------------------------------------------------------------


def test_无评价把档位拉向中性(site_config, gm_factory, user_factory, game_factory, pass_delay):
    """10 位应评人：6 赞 4 无评价 → 赞占比 0.6 好评居多；若按旧口径（6/6）会是好评如潮。"""
    from apps.profiles.services import recompute_player_card

    gm = gm_factory()
    target = user_factory()
    others = [user_factory() for _ in range(9)]
    game = game_factory(gm, [target, *others], finished_at=_closed_at(site_config))
    for reviewer in others[:6]:
        _review(game, reviewer, target, "like")
    pass_delay(target, game.finished_at)

    card = recompute_player_card(target)
    assert (card.reviews_received, card.likes, card.dislikes) == (10, 6, 0)
    assert card.level == levels.MOSTLY_POSITIVE


# --------------------------------------------------------------------------
# 定时任务：窗口关闭后重算
# --------------------------------------------------------------------------


def test_窗口关闭后的计数变化只在定时任务跑过后才进卡(
    site_config, gm_factory, user_factory, game_factory, pass_delay, api_client
):
    from apps.profiles.services import recompute_gm_card, recompute_player_card

    gm = gm_factory()
    target, p1 = user_factory(), user_factory()
    game = game_factory(gm, [target, p1], finished_at=timezone.now() - timedelta(days=5))
    _review(game, p1, target, "like")
    pass_delay(target, game.finished_at)
    pass_delay(gm, game.finished_at)
    recompute_player_card(target)
    recompute_gm_card(gm)
    assert PlayerCard.objects.get(user=target).reviews_received == 1

    # 时间流逝：窗口关了（用缩短窗口模拟）
    site_config.review_window_days = 3
    site_config.save()

    # 定时任务跑之前，缓存卡片与接口都不变（轮询个人空间看不到变化）
    api_client.force_authenticate(target)
    before = api_client.get("/api/v1/profiles/me/player-card/").json()
    assert PlayerCard.objects.get(user=target).reviews_received == 1

    call_command("reviews_window_closing")

    assert PlayerCard.objects.get(user=target).reviews_received == 2  # 1 赞 + GM 无评价
    assert GMCard.objects.get(user=gm).reviews_received == 2  # target 与 p1 都没评 GM
    after = api_client.get("/api/v1/profiles/me/player-card/").json()
    # 未达公布阈值：接口仍一律 null，数字变化不外露
    assert before["reviews_received"] is None and after["reviews_received"] is None

    # 幂等：再跑一次不重复处理，也不出错
    call_command("reviews_window_closing")
    assert PlayerCard.objects.get(user=target).reviews_received == 2


def test_定时任务在窗口关闭但延迟锁未解时不提前计入(
    site_config, gm_factory, user_factory, game_factory, pass_delay
):
    from apps.profiles.services import recompute_player_card

    gm = gm_factory()
    target, p1 = user_factory(), user_factory()
    game = game_factory(gm, [target, p1], finished_at=_closed_at(site_config))

    call_command("reviews_window_closing")
    assert PlayerCard.objects.get(user=target).reviews_received == 0, "延迟锁没解就把无评价算进卡了"

    # 之后又结满三个团（生产路径里 finish_game 会重算到场者的卡）
    pass_delay(target, game.finished_at)
    recompute_player_card(target)
    assert PlayerCard.objects.get(user=target).reviews_received == 2


def test_赞功能关闭时定时任务照样重算计数(
    site_config, gm_factory, user_factory, game_factory, pass_delay
):
    gm = gm_factory()
    target, p1 = user_factory(), user_factory()
    game = game_factory(gm, [target, p1], finished_at=_closed_at(site_config))
    pass_delay(target, game.finished_at)
    site_config.like_feature_enabled = False
    site_config.save()
    call_command("reviews_window_closing")
    card = PlayerCard.objects.get(user=target)
    assert card.reviews_received == 2
    assert card.level == ""


def test_一次性重算命令刷新存量卡片(closed_game):
    target = closed_game["target"]
    PlayerCard.objects.filter(user=target).update(reviews_received=0, likes=0, dislikes=0, level="x")
    GMCard.objects.filter(user=closed_game["gm"]).update(reviews_received=99)

    call_command("reviews_recalc_levels")

    card = PlayerCard.objects.get(user=target)
    assert (card.reviews_received, card.likes, card.dislikes) == (3, 1, 0)
    assert card.level == ""  # 未达公布阈值
    assert GMCard.objects.get(user=closed_game["gm"]).reviews_received == 0  # GM 延迟锁未解
