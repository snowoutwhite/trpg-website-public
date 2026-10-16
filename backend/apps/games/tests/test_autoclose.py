"""`games_autoclose` 命令：三种提醒 + 自动结团 + 惰性状态刷新。"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.games import services
from apps.games.models import GAME_FINISHED, GAME_RUNNING, SIGNUP_ACCEPTED, Game
from apps.notifications import events
from apps.notifications.models import Notification

from .conftest import ago, soon

pytestmark = pytest.mark.django_db


def run_command() -> str:
    out = StringIO()
    call_command("games_autoclose", stdout=out)
    return out.getvalue()


def shift(game: Game, **kwargs) -> Game:
    """直接改数据库里的时间（绕过「截止不得晚于开团」的校验）。"""
    Game.objects.filter(pk=game.pk).update(**kwargs)
    game.refresh_from_db()
    return game


def test_交卡截止前24小时提醒未交卡的人(game_factory, user_factory):
    game = game_factory(start_at=soon(hours=13))
    player = user_factory()
    services.signup(game, player)
    shift(game, card_deadline=soon(hours=12))

    run_command()
    assert Notification.objects.filter(
        recipient=player, event=events.CARD_DEADLINE_REMINDER
    ).count() == 1

    run_command()  # 每团只发一次
    assert Notification.objects.filter(
        recipient=player, event=events.CARD_DEADLINE_REMINDER
    ).count() == 1


def test_已交卡的人不会收到交卡提醒(game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(hours=13))
    player = user_factory()
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    shift(game, card_deadline=soon(hours=12))

    run_command()
    assert not Notification.objects.filter(
        recipient=player, event=events.CARD_DEADLINE_REMINDER
    ).exists()


def test_开团前24小时提醒GM与成功报团者(game_factory, user_factory, card_factory):
    game = game_factory(start_at=soon(hours=12))
    player = user_factory()
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))

    run_command()
    for who in (game.gm, player):
        assert Notification.objects.filter(recipient=who, event=events.GAME_START_REMINDER).count() == 1

    run_command()
    assert Notification.objects.filter(recipient=game.gm, event=events.GAME_START_REMINDER).count() == 1


def test_开团三天后提醒GM结团(game_factory, site_config):
    game = game_factory(start_at=soon(hours=1))
    shift(game, start_at=ago(days=4), card_deadline=ago(days=4))
    assert site_config.auto_close_reminder_days == 3

    run_command()
    game.refresh_from_db()
    assert game.status == GAME_RUNNING  # 到点先流转成进行中
    assert Notification.objects.filter(
        recipient=game.gm, event=events.GAME_CLOSE_REMINDER
    ).count() == 1

    run_command()
    assert Notification.objects.filter(
        recipient=game.gm, event=events.GAME_CLOSE_REMINDER
    ).count() == 1


def test_开团七天后自动结团到场名单等于全部成功报团者(
    game_factory, user_factory, card_factory, site_config
):
    game = game_factory(start_at=soon(hours=1))
    player = user_factory()
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED
    assert site_config.auto_close_days == 7

    shift(game, start_at=ago(days=8), card_deadline=ago(days=8))
    run_command()

    game.refresh_from_db()
    record.refresh_from_db()
    assert game.status == GAME_FINISHED
    assert game.auto_closed is True
    assert record.attended is True
    # 自动结团要发预警给 GM，评价开放通知照常
    assert Notification.objects.filter(recipient=game.gm, event=events.AUTO_CLOSE_WARNING).exists()
    assert Notification.objects.filter(recipient=player, event=events.REVIEW_OPENED).exists()
    # 次数照常计
    from apps.profiles.services import ensure_player_card

    assert ensure_player_card(player).games_played == 1


def test_自动结团幂等不会重复计数(game_factory, user_factory, card_factory):
    from apps.profiles.services import ensure_player_card

    game = game_factory(start_at=soon(hours=1))
    player = user_factory()
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    shift(game, start_at=ago(days=8), card_deadline=ago(days=8))

    run_command()
    run_command()

    assert ensure_player_card(player).games_played == 1
    assert Notification.objects.filter(recipient=player, event=events.REVIEW_OPENED).count() == 1


def test_截止后没交卡的会被标记(game_factory, user_factory):
    from apps.games.models import SIGNUP_NO_CARD

    game = game_factory(start_at=soon(days=2))
    player = user_factory()
    record = services.signup(game, player)
    shift(game, card_deadline=ago(hours=1))

    output = run_command()
    record.refresh_from_db()
    assert record.status == SIGNUP_NO_CARD
    assert "未交卡标记=1" in output


def test_命令输出各步条数(game_factory):
    output = run_command()
    for key in ("进行中=", "交卡提醒=", "开团提醒=", "结团提醒=", "自动结团=", "未交卡标记="):
        assert key in output
