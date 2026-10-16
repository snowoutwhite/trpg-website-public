"""交卡流程：先到先得即通过、PL 池审批、免交卡、截止、GM 代传、卡的下载权。"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.charactercards.models import STATUS_TORN
from apps.games import services
from apps.games.models import (
    SIGNUP_ACCEPTED,
    SIGNUP_NO_CARD,
    SIGNUP_POOL_REVIEW,
    SIGNUP_REJECTED,
    SIGNUP_SUBMITTED,
    Game,
)
from apps.notifications import events
from apps.notifications.models import Notification

from .conftest import ago, soon, upload

pytestmark = pytest.mark.django_db


def submit_url(game: Game) -> str:
    return f"/api/v1/games/{game.pk}/submit-card/"


def download_url(card) -> str:
    return f"/api/v1/charactercards/{card.pk}/download/"


# --------------------------------------------------------------------------
# 两种报名模式
# --------------------------------------------------------------------------


def test_先到先得交卡即通过(api_client, signed_up, card_factory):
    game, player, record = signed_up()
    card = card_factory(player)

    api_client.force_authenticate(player)
    response = api_client.post(submit_url(game), {"card_id": card.pk}, format="json")

    assert response.status_code == 200
    assert response.json()["status"] == SIGNUP_ACCEPTED
    record.refresh_from_db()
    assert record.card_id == card.pk
    assert record.card_submitted_at is not None
    # 有人交卡要通知 GM，审批结果要通知 PL
    assert Notification.objects.filter(recipient=game.gm, event=events.CARD_SUBMITTED).exists()
    assert Notification.objects.filter(recipient=player, event=events.CARD_REVIEW_RESULT).exists()


def test_PL池模式交卡进待审再由GM通过(api_client, signed_up, card_factory):
    game, player, record = signed_up(signup_mode=SIGNUP_POOL_REVIEW)
    services.submit_card(record, card_factory(player))
    record.refresh_from_db()
    assert record.status == SIGNUP_SUBMITTED

    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/review/",
        {"approved": True, "note": "卡没问题"},
        format="json",
    )
    assert response.status_code == 200
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED
    assert record.review_note == "卡没问题"


def test_PL池模式可以驳回(signed_up, card_factory):
    game, player, record = signed_up(signup_mode=SIGNUP_POOL_REVIEW)
    services.submit_card(record, card_factory(player))
    services.review_signup(record, approved=False, note="规则不匹配")

    record.refresh_from_db()
    assert record.status == SIGNUP_REJECTED
    assert Notification.objects.filter(
        recipient=player, event=events.CARD_REVIEW_RESULT
    ).exists()


def test_免交卡团不接受交卡(signed_up, card_factory):
    game, player, record = signed_up(requires_card=False)
    assert record.status == SIGNUP_ACCEPTED
    with pytest.raises(services.CardNotRequired):
        services.submit_card(record, card_factory(player))


# --------------------------------------------------------------------------
# 截止
# --------------------------------------------------------------------------


def test_截止后不能交卡(api_client, signed_up, card_factory):
    game, player, record = signed_up()
    Game.objects.filter(pk=game.pk).update(card_deadline=ago(hours=1))

    api_client.force_authenticate(player)
    response = api_client.post(submit_url(game), {"card_id": card_factory(player).pk}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_deadline_passed"


def test_截止后未交卡被标为未交卡并可由GM处置(signed_up):
    game, player, record = signed_up()
    Game.objects.filter(pk=game.pk).update(card_deadline=ago(hours=1))
    game.refresh_from_db()

    assert services.mark_no_card_signups(game) == 1
    record.refresh_from_db()
    assert record.status == SIGNUP_NO_CARD
    # 再跑一次不会重复标记，也就不会重复发通知
    assert services.mark_no_card_signups(game) == 0
    assert (
        Notification.objects.filter(recipient=player, event=events.CARD_REVIEW_RESULT).count() == 1
    )

    services.review_signup(record, approved=True, note="口头确认用预设卡")
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED


def test_撕掉的卡不能用于交卡(signed_up, card_factory):
    game, player, record = signed_up()
    card = card_factory(player)
    card.status = STATUS_TORN
    card.save(update_fields=["status"])

    with pytest.raises(services.CardNotUsable):
        services.submit_card(record, card)


def test_不能交别人的卡(api_client, signed_up, card_factory, user_factory):
    game, player, record = signed_up()
    someone_else = user_factory()
    others_card = card_factory(someone_else)

    api_client.force_authenticate(player)
    response = api_client.post(submit_url(game), {"card_id": others_card.pk}, format="json")
    assert response.status_code == 404  # 按 owner 过滤，不泄露这张卡存在


# --------------------------------------------------------------------------
# GM 代传卡
# --------------------------------------------------------------------------


def test_GM代传卡归PL并标GM上传(api_client, signed_up):
    from apps.charactercards.models import CharacterCard

    game, player, record = signed_up()
    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/upload-card/",
        {"file": upload(), "name": "GM 代传的卡"},
        format="multipart",
    )

    assert response.status_code == 201
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED
    assert record.card_uploaded_by_gm is True

    card = CharacterCard.objects.get(pk=record.card_id)
    assert card.owner_id == player.pk  # 卡归 PL
    assert card.is_public is False
    assert card.files.first().uploaded_by_gm is True


def test_非本团GM不能代传卡(api_client, signed_up, gm_factory):
    game, player, record = signed_up()
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/upload-card/",
        {"file": upload()},
        format="multipart",
    )
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_game_gm"


# --------------------------------------------------------------------------
# 交上来的卡：同团 GM 能下载，别人不能
# --------------------------------------------------------------------------


def test_同团GM可以下载PL交上来的私密卡(api_client, signed_up, card_factory):
    game, player, record = signed_up()
    card = card_factory(player, is_public=False)
    services.submit_card(record, card)

    api_client.force_authenticate(game.gm)
    response = api_client.get(download_url(card))
    assert response.status_code == 200


def test_非同团的人不能下载别人的私密卡(api_client, signed_up, card_factory, gm_factory, user_factory):
    game, player, record = signed_up()
    card = card_factory(player, is_public=False)
    services.submit_card(record, card)

    # W5 状态码统一：看不见的私密卡一律 404（不承认它存在），游客同理。
    for outsider in (gm_factory(), user_factory()):
        api_client.force_authenticate(outsider)
        assert api_client.get(download_url(card)).status_code == 404

    api_client.force_authenticate(user=None)
    assert api_client.get(download_url(card)).status_code == 404


def test_只交到别的团的卡不给这个GM看(signed_up, card_factory, gm_factory, game_factory):
    """file access checker 只认「交到我手上」的卡，不是「我是 GM」就都能看。"""
    game, player, record = signed_up()
    card = card_factory(player, is_public=False)
    services.submit_card(record, card)

    other_gm = gm_factory()
    assert services.gm_can_view_submitted_card(other_gm, card) is False
    assert services.gm_can_view_submitted_card(game.gm, card) is True


def test_退出后GM不再能下载那张卡(signed_up, card_factory):
    game, player, record = signed_up()
    card = card_factory(player, is_public=False)
    services.submit_card(record, card)
    services.withdraw(record, now=timezone.now())

    assert services.gm_can_view_submitted_card(game.gm, card) is False


def test_卡的参团记录带上团名(signed_up, card_factory):
    from apps.charactercards.services import games_played_for

    game, player, record = signed_up(start_at=soon(hours=1))
    card = card_factory(player)
    services.submit_card(record, card)
    record.refresh_from_db()
    services.finish_game(game, attended_signup_ids=[record.pk])

    played = games_played_for(card)
    assert len(played) == 1
    assert played[0]["title"] == game.title


# --------------------------------------------------------------------------
# 缺陷 D3（空壳卡）：交卡必须真的有文件
#
# 复现路径：PL 在 /me/cards 只填名称建卡、不传文件，
# 回团详情能选到它、交卡 200、GM 在名单里看到卡名与下载链接，点开却是 404
# card_file_missing —— GM 以为收到卡了，实际什么都没有。
# --------------------------------------------------------------------------


def test_没有文件的空壳卡不能交(api_client, signed_up, card_factory):
    game, player, record = signed_up()
    empty = card_factory(player, with_file=False, name="只填了名字的卡")
    assert empty.has_file is False  # 证伪前提：这张卡确实是空的

    api_client.force_authenticate(player)
    response = api_client.post(submit_url(game), {"card_id": empty.pk}, format="json")

    assert response.status_code == 400
    #  拆码：交卡这一处从 `card_file_missing` 改成 `signup_card_file_missing`，
    # 与 charactercards 下载口「这张卡还没有文件」的 `card_file_missing` 分开。
    assert response.json()["error"]["code"] == "signup_card_file_missing"
    record.refresh_from_db()
    assert record.card_id is None
    assert record.status != SIGNUP_ACCEPTED


def test_给空壳卡补上文件之后就能交了(api_client, signed_up, card_factory):
    """对照组：把上一条的唯一差异（有没有文件）翻过来，必须变成成功。

    少了这一条，上面那条在「交卡整个坏掉」时也会通过。
    """
    from apps.charactercards import services as card_services

    game, player, record = signed_up()
    card = card_factory(player, with_file=False)
    card_services.add_file_version(card, upload(), uploaded_by=player)

    api_client.force_authenticate(player)
    response = api_client.post(submit_url(game), {"card_id": card.pk}, format="json")

    assert response.status_code == 200
    record.refresh_from_db()
    assert record.card_id == card.pk


def test_空壳卡的is_usable_for_signup为假(card_factory, user_factory):
    """`is_usable_for_signup` 是前端交卡下拉的过滤依据，必须把空壳卡排除在外。"""
    from apps.charactercards import services as card_services

    owner = user_factory()
    empty = card_factory(owner, with_file=False)
    assert empty.is_usable_for_signup is False

    card_services.add_file_version(empty, upload(), uploaded_by=owner)
    assert empty.is_usable_for_signup is True

    empty.status = STATUS_TORN
    empty.save(update_fields=["status"])
    assert empty.is_usable_for_signup is False  # 撕卡这一条原有口径不能被覆盖掉


def test_空壳卡交卡失败时GM名单里不会出现这张卡(api_client, signed_up, card_factory):
    """站在 GM 那一侧复核：名单里不能挂一张点开是 404 的卡。"""
    game, player, record = signed_up()
    empty = card_factory(player, with_file=False, name="幽灵卡")

    api_client.force_authenticate(player)
    api_client.post(submit_url(game), {"card_id": empty.pk}, format="json")

    api_client.force_authenticate(game.gm)
    roster = api_client.get(f"/api/v1/games/{game.pk}/roster/")
    assert roster.status_code == 200
    body = roster.json()
    assert body["is_gm"] is True
    assert "幽灵卡" not in str(body)
    assert all(row["card"] is None for row in body["results"])


def test_GM代传卡落地后卡一定有文件(signed_up, gm_factory):
    """代传这条路本来就带着文件，这里钉住后置校验，防止将来被改松。"""
    game, player, record = signed_up()
    record = services.gm_upload_card(record, upload("代传.pdf"), gm=game.gm, name="GM 代传的卡")

    assert record.card is not None
    assert record.card.has_file is True
    assert record.card.is_usable_for_signup is True
    assert record.card_uploaded_by_gm is True
