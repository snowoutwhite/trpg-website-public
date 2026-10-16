"""五档统计刷新：GM 侧与 PL 侧分开进卡，档位只在被评次数 ≥ 公布阈值时公布。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.profiles import levels
from apps.profiles.models import GMCard, PlayerCard
from apps.reviews import services
from apps.reviews.models import ReviewWindowNotice

pytestmark = pytest.mark.django_db


def test_评价统计滞后于延迟锁_延迟过后才进卡(
    user_factory, gm_factory, game_factory, submit, pass_delay
):
    """W5：统计只计「已对被评者可见」（已过 3 团延迟）的评价。

    改口径的理由：统计一旦实时，被评者轮询自己的卡就能读出「刚才有人评了我」，
    等于绕过 17.2 的时间锁（W3 红队复现）。代价是公开声望滞后 3 团。
    """
    from apps.profiles.services import recompute_player_card

    gm = gm_factory()
    reviewee = user_factory()
    game = game_factory(gm, [reviewee])

    submit(gm, game, reviewee, verdict="like")

    card = PlayerCard.objects.get(user=reviewee)
    assert (card.reviews_received, card.likes, card.dislikes) == (0, 0, 0), "延迟没过就进卡了"

    pass_delay(reviewee, game.finished_at)
    recompute_player_card(reviewee)
    card.refresh_from_db()
    assert (card.reviews_received, card.likes, card.dislikes) == (1, 1, 0)
    # 未达公布阈值（默认 10）时档位为空，赞/倒赞的绝对值也不外露（profiles 负责）
    assert card.level == ""


def test_GM侧与PL侧分别统计(user_factory, gm_factory, game_factory, submit, pass_delay):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    # W5：统计只计已过延迟的评价，两位被评者都得先跨过延迟锁。
    pass_delay(gm, game.finished_at)
    pass_delay(player, game.finished_at)

    submit(player, game, gm, verdict="like")  # 评的是 GM
    submit(gm, game, player, verdict="dislike")  # 评的是 PL

    gm_card = GMCard.objects.get(user=gm)
    gm_player_card = PlayerCard.objects.get(user=gm)
    player_card = PlayerCard.objects.get(user=player)

    assert (gm_card.reviews_received, gm_card.likes) == (1, 1)
    assert gm_player_card.reviews_received == 0  # GM 收到的不进他自己的玩家卡
    assert (player_card.reviews_received, player_card.dislikes) == (1, 1)


def test_达到公布阈值后公布五档(user_factory, gm_factory, game_factory, site_config, pass_delay):
    gm = gm_factory()
    reviewee = user_factory()
    reviewers = [user_factory() for _ in range(site_config.like_level_publish_threshold)]
    game = game_factory(gm, [reviewee, *reviewers])
    pass_delay(reviewee, game.finished_at)  # W5：统计只计已过延迟的评价

    for index, reviewer in enumerate(reviewers):
        services.upsert_review(
            reviewer,
            game=game,
            reviewee=reviewee,
            verdict="like" if index < 8 else "dislike",
            text=f"第 {index} 条",
        )

    card = PlayerCard.objects.get(user=reviewee)
    assert card.reviews_received == 10
    assert (card.likes, card.dislikes) == (8, 2)
    assert card.level == levels.OVERWHELMINGLY_POSITIVE  # 赞占比 0.8


def test_窗口即将关闭提醒每团一次且只发给还没评完的人(
    user_factory, gm_factory, game_factory, submit, site_config
):
    from apps.notifications import events
    from apps.notifications.models import Notification

    gm = gm_factory()
    done, pending = user_factory(), user_factory()
    finished_at = timezone.now() - timedelta(days=site_config.review_window_days) + timedelta(hours=12)
    game = game_factory(gm, [done, pending], finished_at=finished_at)
    # done 把两个对象都评完了，pending 一个没评
    submit(done, game, gm)
    submit(done, game, pending)

    call_command("reviews_window_closing")
    call_command("reviews_window_closing")  # 幂等：第二次不再发

    sent = Notification.objects.filter(event=events.REVIEW_WINDOW_CLOSING)
    assert set(sent.values_list("recipient_id", flat=True)) == {gm.pk, pending.pk}
    assert sent.count() == 2
    assert ReviewWindowNotice.objects.filter(game=game).count() == 1
    # 通知里不含任何评价人线索
    for notification in sent:
        assert notification.actor_id is None
        assert set(notification.payload) == {"game_title", "ends_at", "pending"}


def test_关闭赞功能时不发窗口提醒(gm_factory, user_factory, game_factory, site_config):
    from apps.notifications.models import Notification

    gm = gm_factory()
    player = user_factory()
    finished_at = timezone.now() - timedelta(days=site_config.review_window_days) + timedelta(hours=12)
    game_factory(gm, [player], finished_at=finished_at)

    site_config.like_feature_enabled = False
    site_config.save()
    call_command("reviews_window_closing")

    assert not Notification.objects.exists()
