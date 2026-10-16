"""可见性：游客只见精选，登录用户见公开 + 自己同团的 same_game。"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.reports.models import VISIBILITY_PUBLIC, VISIBILITY_SAME_GAME

pytestmark = pytest.mark.django_db

LIST_URL = reverse("v1:reports:report-list")
FEATURED_URL = reverse("v1:reports:report-featured")


def _ids(response) -> set[int]:
    return {row["id"] for row in response.json()["results"]}


@pytest.fixture
def world(game_factory, attendee_factory, report_factory, user_factory):
    """一个团、一个到场 PL、三份战报（精选公开 / 普通公开 / 仅同团）。"""
    game = game_factory()
    member = attendee_factory(game)
    other = attendee_factory(game)
    outsider = user_factory()

    featured = report_factory(game, member, title="精选", is_featured=True)
    public = report_factory(game, other, title="公开")
    same_game = report_factory(
        game_factory(gm=game.gm), game.gm, title="仅同团", visibility=VISIBILITY_SAME_GAME
    )
    return {
        "game": game,
        "member": member,
        "other": other,
        "outsider": outsider,
        "featured": featured,
        "public": public,
        "same_game": same_game,
    }


def test_guest_sees_only_featured_public(api_client, world):
    response = api_client.get(LIST_URL)

    assert response.status_code == 200
    assert _ids(response) == {world["featured"].pk}


def test_guest_detail_404_for_non_featured(api_client, world):
    assert api_client.get(reverse("v1:reports:report-detail", args=[world["public"].pk])).status_code == 404
    assert api_client.get(reverse("v1:reports:report-detail", args=[world["featured"].pk])).status_code == 200


def test_featured_report_must_also_be_public(api_client, world, report_factory):
    """精选了但作者选的是「仅同团」时，游客仍然看不到。"""
    hidden = report_factory(
        world["game"],
        world["game"].gm,
        title="精选但仅同团",
        visibility=VISIBILITY_SAME_GAME,
        is_featured=True,
    )

    assert hidden.pk not in _ids(api_client.get(LIST_URL))
    assert hidden.pk not in _ids(api_client.get(FEATURED_URL))
    assert api_client.get(reverse("v1:reports:report-detail", args=[hidden.pk])).status_code == 404


def test_logged_in_outsider_sees_public_but_not_same_game(api_client, world):
    api_client.force_authenticate(world["outsider"])

    assert _ids(api_client.get(LIST_URL)) == {world["featured"].pk, world["public"].pk}
    detail = reverse("v1:reports:report-detail", args=[world["same_game"].pk])
    assert api_client.get(detail).status_code == 404


def test_teammate_sees_same_game_report(api_client, world, attendee_factory):
    teammate = attendee_factory(world["same_game"].game)
    api_client.force_authenticate(teammate)

    detail = reverse("v1:reports:report-detail", args=[world["same_game"].pk])
    assert api_client.get(detail).status_code == 200
    assert world["same_game"].pk in _ids(api_client.get(LIST_URL))


def test_author_always_sees_own_report(api_client, world):
    api_client.force_authenticate(world["same_game"].author)

    detail = reverse("v1:reports:report-detail", args=[world["same_game"].pk])
    assert api_client.get(detail).status_code == 200


def test_filter_by_game(api_client, world):
    api_client.force_authenticate(world["member"])

    response = api_client.get(LIST_URL, {"game": world["game"].pk})

    assert _ids(response) == {world["featured"].pk, world["public"].pk}


def test_no_email_in_payload(api_client, world):
    """作者一律用公开表示，响应里不得出现邮箱。"""
    api_client.force_authenticate(world["member"])

    body = api_client.get(reverse("v1:reports:report-detail", args=[world["public"].pk])).content.decode()

    assert world["other"].email not in body
    assert "email" not in body


def test_only_author_can_edit(api_client, world):
    api_client.force_authenticate(world["other"])
    url = reverse("v1:reports:report-detail", args=[world["featured"].pk])

    assert api_client.patch(url, {"title": "改别人的"}, format="json").status_code == 403
    assert api_client.delete(url).status_code == 403


def test_author_and_moderator_can_delete(api_client, world, moderator, report_factory):
    from apps.reports.models import Report

    api_client.force_authenticate(world["member"])
    assert api_client.delete(
        reverse("v1:reports:report-detail", args=[world["featured"].pk])
    ).status_code == 204

    api_client.force_authenticate(moderator)
    assert api_client.delete(
        reverse("v1:reports:report-detail", args=[world["public"].pk])
    ).status_code == 204
    assert not Report.objects.filter(pk=world["public"].pk).exists()


def test_featured_flag_not_settable_from_api(api_client, world):
    """精选只有站主在后台能打，前台改不动。"""
    api_client.force_authenticate(world["public"].author)
    url = reverse("v1:reports:report-detail", args=[world["public"].pk])

    response = api_client.patch(url, {"is_featured": True}, format="json")

    world["public"].refresh_from_db()
    assert response.status_code == 200
    assert world["public"].is_featured is False


def test_author_can_switch_visibility(api_client, world):
    api_client.force_authenticate(world["public"].author)
    url = reverse("v1:reports:report-detail", args=[world["public"].pk])

    response = api_client.patch(url, {"visibility": VISIBILITY_SAME_GAME}, format="json")

    assert response.status_code == 200
    world["public"].refresh_from_db()
    assert world["public"].visibility == VISIBILITY_SAME_GAME
    # 切成仅同团后，非同团的登录用户就看不到了
    api_client.force_authenticate(world["outsider"])
    assert api_client.get(url).status_code == 404
    # 也不再出现在游客列表里（即便被精选过）
    api_client.force_authenticate(None)
    assert world["public"].pk not in _ids(api_client.get(LIST_URL))


def test_visibility_choices_are_only_two(api_client, world):
    api_client.force_authenticate(world["public"].author)
    url = reverse("v1:reports:report-detail", args=[world["public"].pk])

    response = api_client.patch(url, {"visibility": VISIBILITY_PUBLIC + "x"}, format="json")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 封禁作者读自己的战报：列表与详情同一口径
#

# 按游客算，**作者本人也不例外**。修前 `can_view()` 先判作者本人再判封禁，
# 列表不给、详情却 200。
# ---------------------------------------------------------------------------


def _banned(user):
    from apps.accounts.services import ban_user

    ban_user(user, reason="违规")
    return type(user).objects.get(pk=user.pk)


def test_封禁作者读自己的同团战报_列表与详情都按游客算(api_client, world):
    author = world["game"].gm  # `same_game` 那份的作者
    own = world["same_game"]
    api_client.force_authenticate(author)
    assert api_client.get(reverse("v1:reports:report-detail", args=[own.pk])).status_code == 200, "前置：封禁前本人看得见"

    api_client.force_authenticate(_banned(author))
    assert own.pk not in _ids(api_client.get(LIST_URL))
    assert api_client.get(reverse("v1:reports:report-detail", args=[own.pk])).status_code == 404


def test_封禁作者读自己的公开战报_未精选404_精选200(api_client, world):
    """公开战报同理：游客只见「精选 + 公开」，封禁作者本人也一样，列表与详情一致。"""
    public = world["public"]  # 作者 other，公开、未精选
    featured = world["featured"]  # 作者 member，公开、精选
    for report in (public, featured):
        api_client.force_authenticate(_banned(report.author))
        listed = report.pk in _ids(api_client.get(LIST_URL))
        detail = api_client.get(reverse("v1:reports:report-detail", args=[report.pk])).status_code
        if report.is_featured:
            assert listed and detail == 200
        else:
            assert not listed and detail == 404
