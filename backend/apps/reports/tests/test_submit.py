"""提交条件、每人每团一份、积分只发一次。"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.games.models import GAME_RUNNING
from apps.points import services as points_services
from apps.points.models import REASON_REPORT_SUBMITTED, PointsLedger
from apps.reports.models import Report
from apps.reports.services import POINTS_PER_REPORT

pytestmark = pytest.mark.django_db


def _payload(game, **extra):
    data = {"game": game.pk, "title": "第一次深潜", "body_markdown": "# 正文"}
    data.update(extra)
    return data


def test_attendee_can_submit(api_client, game_factory, attendee_factory):
    game = game_factory()
    player = attendee_factory(game)
    api_client.force_authenticate(player)

    response = api_client.post(reverse("v1:reports:report-list"), _payload(game), format="json")

    assert response.status_code == 201
    assert Report.objects.filter(game=game, author=player).exists()


def test_gm_can_submit_without_signup_row(api_client, game_factory):
    """本团 GM 没有报名行，但也算「在团内到场」。"""
    game = game_factory()
    api_client.force_authenticate(game.gm)

    response = api_client.post(reverse("v1:reports:report-list"), _payload(game), format="json")

    assert response.status_code == 201


def test_non_attendee_forbidden(api_client, game_factory, attendee_factory, user_factory):
    game = game_factory()
    # 报了名但没到场
    absent = attendee_factory(game, attended=False)
    outsider = user_factory()

    for user in (absent, outsider):
        api_client.force_authenticate(user)
        response = api_client.post(reverse("v1:reports:report-list"), _payload(game), format="json")
        assert response.status_code == 403, user.nickname
        assert response.json()["error"]["code"] == "not_in_game"


def test_unfinished_game_forbidden(api_client, game_factory, attendee_factory):
    game = game_factory(status=GAME_RUNNING)
    player = attendee_factory(game)
    api_client.force_authenticate(player)

    response = api_client.post(reverse("v1:reports:report-list"), _payload(game), format="json")

    # W5 状态码统一：「团还没结团」是目标状态不对 → 400（与 reviews 的 review_not_open、
    # games 的 invalid_game_status 同档）；403 留给身份/角色类拒绝。
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "game_not_finished"


def test_guest_cannot_submit(api_client, game_factory):
    game = game_factory()
    response = api_client.post(reverse("v1:reports:report-list"), _payload(game), format="json")
    assert response.status_code in (401, 403)
    assert not Report.objects.exists()


def test_second_post_updates_the_same_report(api_client, game_factory, attendee_factory):
    """每人每团一份：第二次 POST 是更新同一份，不是新建第二份。"""
    game = game_factory()
    player = attendee_factory(game)
    api_client.force_authenticate(player)
    url = reverse("v1:reports:report-list")

    first = api_client.post(url, _payload(game), format="json")
    second = api_client.post(
        url, _payload(game, title="补记", body_markdown="合并后的正文"), format="json"
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert Report.objects.filter(game=game, author=player).count() == 1
    assert Report.objects.get(pk=first.json()["id"]).body_markdown == "合并后的正文"


def test_points_granted_once(api_client, game_factory, attendee_factory):
    game = game_factory()
    player = attendee_factory(game)
    api_client.force_authenticate(player)
    url = reverse("v1:reports:report-list")

    api_client.post(url, _payload(game), format="json")
    api_client.post(url, _payload(game, title="改一版"), format="json")
    api_client.patch(
        reverse("v1:reports:report-detail", args=[Report.objects.get().pk]),
        {"title": "再改一版"},
        format="json",
    )

    entries = PointsLedger.objects.filter(user=player, reason=REASON_REPORT_SUBMITTED)
    assert entries.count() == 1
    assert points_services.balance(player) == POINTS_PER_REPORT


def test_deleting_report_keeps_points_and_rewrite_does_not_refarm(
    api_client, game_factory, attendee_factory
):
    """删战报不自动撤积分（撤销只由站主做）；删了重写也不会二次发分。"""
    game = game_factory()
    player = attendee_factory(game)
    api_client.force_authenticate(player)
    url = reverse("v1:reports:report-list")

    created = api_client.post(url, _payload(game), format="json")
    api_client.delete(reverse("v1:reports:report-detail", args=[created.json()["id"]]))
    assert points_services.balance(player) == POINTS_PER_REPORT

    api_client.post(url, _payload(game, title="重写一份"), format="json")
    assert points_services.balance(player) == POINTS_PER_REPORT
    assert PointsLedger.objects.filter(user=player).count() == 1


def test_body_length_capped(api_client, game_factory, attendee_factory):
    from apps.reports.models import BODY_MAX_LENGTH

    game = game_factory()
    player = attendee_factory(game)
    api_client.force_authenticate(player)

    response = api_client.post(
        reverse("v1:reports:report-list"),
        _payload(game, body_markdown="灌" * (BODY_MAX_LENGTH + 1)),
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_markdown_is_stored_verbatim(api_client, game_factory, attendee_factory):
    """正文按原文存储，服务端不渲染也不改写（sanitize 是前端的事）。"""
    game = game_factory()
    player = attendee_factory(game)
    api_client.force_authenticate(player)
    raw = "# 标题\n<script>alert(1)</script>\n[链接](javascript:alert(2))"

    response = api_client.post(
        reverse("v1:reports:report-list"), _payload(game, body_markdown=raw), format="json"
    )

    assert response.status_code == 201
    assert Report.objects.get().body_markdown == raw
    assert response.json()["body_markdown"] == raw
