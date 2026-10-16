"""对抗测试：名单三层可见性与隐私字段泄露。"""

from __future__ import annotations

import json

import pytest

from apps.games import services
from apps.games.models import SIGNUP_ACCEPTED

from .conftest import soon

pytestmark = pytest.mark.django_db


def _text(response) -> str:
    """把响应体压成一整段文本，用于「全文不得出现某串」的黑盒扫描。"""
    return json.dumps(response.json(), ensure_ascii=False)


@pytest.fixture
def populated_game(game_factory, user_factory, card_factory):
    """一个团：1 个已通过（accepted）、1 个待交卡（pending）、1 个被拒（rejected）。"""
    game = game_factory(max_players=5)
    accepted_pl = user_factory(nickname="已过卡的人", email="accepted@example.com")
    pending_pl = user_factory(nickname="还没交卡的人", email="pending@example.com")
    rejected_pl = user_factory(nickname="被拒的人", email="rejected@example.com")

    accepted = services.signup(game, accepted_pl)
    services.submit_card(accepted, card_factory(accepted_pl))
    assert accepted.status == SIGNUP_ACCEPTED

    pending = services.signup(game, pending_pl)

    rejected = services.signup(game, rejected_pl)
    services.review_signup(rejected, approved=False, note="你雷点太多，不收")

    game.refresh_from_db()
    return {
        "game": game,
        "accepted": (accepted_pl, accepted),
        "pending": (pending_pl, pending),
        "rejected": (rejected_pl, rejected),
    }


# --------------------------------------------------------------------------
# 第一层：游客
# --------------------------------------------------------------------------


def test_游客拿团详情刮不到任何报名者身份(api_client, populated_game):
    game = populated_game["game"]
    response = api_client.get(f"/api/v1/games/{game.pk}/")
    assert response.status_code == 200
    body = _text(response)

    for key in ("accepted", "pending", "rejected"):
        player, _ = populated_game[key]
        assert player.nickname not in body, f"游客看到了报名者昵称：{player.nickname}"
        assert player.email not in body
    assert response.json()["my_signup"] is None
    # 只给数字，不给身份
    assert response.json()["accepted_count"] == 1


def test_游客拿列表刮不到任何报名者身份(api_client, populated_game):
    response = api_client.get("/api/v1/games/")
    assert response.status_code == 200
    body = _text(response)
    for key in ("accepted", "pending", "rejected"):
        player, _ = populated_game[key]
        assert player.nickname not in body
        assert player.email not in body


@pytest.mark.parametrize("path", ["signups/", "roster/"])
def test_游客要名单一律401(api_client, populated_game, path):
    game = populated_game["game"]
    response = api_client.get(f"/api/v1/games/{game.pk}/{path}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


# --------------------------------------------------------------------------
# 第二层：登录但非同团
# --------------------------------------------------------------------------


def test_登录非同团拿不到正式名单(api_client, populated_game, user_factory):
    game = populated_game["game"]
    api_client.force_authenticate(user_factory(nickname="路人甲"))
    response = api_client.get(f"/api/v1/games/{game.pk}/roster/")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_登录非同团的招募中名单不含accepted者身份与卡(api_client, populated_game, user_factory):
    """招募中名单只该有「还没定下来的人」；accepted 与 rejected 都不能出现。"""
    game = populated_game["game"]
    api_client.force_authenticate(user_factory(nickname="路人乙"))
    response = api_client.get(f"/api/v1/games/{game.pk}/signups/")
    assert response.status_code == 200
    body = _text(response)

    accepted_pl, _ = populated_game["accepted"]
    rejected_pl, _ = populated_game["rejected"]
    pending_pl, _ = populated_game["pending"]

    assert pending_pl.nickname in body
    assert accepted_pl.nickname not in body, "非同团用户看到了正式名单里的人"
    assert rejected_pl.nickname not in body, "非同团用户看到了被拒的人"
    # 卡与审批线索一概不给
    for leak in ("card", "download_url", "review_note", "attended"):
        assert leak not in body, f"招募中名单泄露了 {leak}"


def test_被拒者拿不到正式名单(api_client, populated_game):
    """被 GM 拒掉的人不是同团成员。"""
    game = populated_game["game"]
    rejected_pl, _ = populated_game["rejected"]
    api_client.force_authenticate(rejected_pl)
    assert api_client.get(f"/api/v1/games/{game.pk}/roster/").status_code == 403


def test_待交卡者拿不到正式名单(api_client, populated_game):
    """pending 只是占位，还不是「审卡通过」。"""
    game = populated_game["game"]
    pending_pl, _ = populated_game["pending"]
    api_client.force_authenticate(pending_pl)
    assert api_client.get(f"/api/v1/games/{game.pk}/roster/").status_code == 403


# --------------------------------------------------------------------------
# 第三层：同团 PL
# --------------------------------------------------------------------------


def test_同团PL看不到别人的审批备注与卡(api_client, populated_game, user_factory, card_factory):
    """PL 视角的正式名单：只有昵称/头像/顺序，绝不含 review_note 与卡。"""
    game = populated_game["game"]
    other = user_factory(nickname="另一个同团")
    other_signup = services.signup(game, other)
    services.submit_card(other_signup, card_factory(other))
    services.review_signup(other_signup, approved=True, note="这人我认识，放行")

    me, _ = populated_game["accepted"]
    api_client.force_authenticate(me)
    response = api_client.get(f"/api/v1/games/{game.pk}/roster/")
    assert response.status_code == 200
    body = _text(response)

    assert response.json()["is_gm"] is False
    assert other.nickname in body  # 同团名单本来就该看到
    assert "这人我认识，放行" not in body, "同团 PL 看到了 GM 的审批备注"
    assert "review_note" not in body
    assert "download_url" not in body, "同团 PL 拿到了别人私密卡的下载地址"
    assert '"card"' not in body


def test_名单接口全文不含邮箱与账号状态字段(api_client, populated_game, user_factory, card_factory):
    """三个名单接口的 JSON 全文黑盒扫描：邮箱 / is_banned / is_muted / password 一律不得出现。"""
    game = populated_game["game"]
    me, _ = populated_game["accepted"]

    targets = [
        (me, f"/api/v1/games/{game.pk}/signups/"),
        (me, f"/api/v1/games/{game.pk}/roster/"),
        (game.gm, f"/api/v1/games/{game.pk}/roster/"),  # GM 全量视图也要扫
        (game.gm, f"/api/v1/games/{game.pk}/"),
    ]
    for viewer, path in targets:
        api_client.force_authenticate(viewer)
        response = api_client.get(path)
        assert response.status_code == 200, path
        body = _text(response)
        for key in ("accepted", "pending", "rejected"):
            player, _ = populated_game[key]
            assert player.email not in body, f"{path} 泄露了邮箱"
        for leak in ("is_banned", "is_muted", "is_deactivated", "password", "last_login"):
            assert leak not in body, f"{path} 泄露了 {leak}"


def test_GM面板才拿得到卡与备注(api_client, populated_game):
    """正向对照：确认上面几条不是因为接口本来就没数据。"""
    game = populated_game["game"]
    api_client.force_authenticate(game.gm)
    response = api_client.get(f"/api/v1/games/{game.pk}/roster/")
    assert response.status_code == 200
    body = _text(response)
    assert response.json()["is_gm"] is True
    assert "你雷点太多，不收" in body
    assert "download_url" in body


def test_别的GM拿不到本团正式名单(api_client, populated_game, gm_factory):
    game = populated_game["game"]
    api_client.force_authenticate(gm_factory(nickname="隔壁GM"))
    response = api_client.get(f"/api/v1/games/{game.pk}/roster/")
    assert response.status_code == 403


def test_我的报名接口只回自己的记录(api_client, populated_game):
    game = populated_game["game"]
    me, mine = populated_game["accepted"]
    api_client.force_authenticate(me)
    response = api_client.get("/api/v1/games/my-signups/")
    assert response.status_code == 200
    ids = [row["id"] for row in response.json()["results"]]
    assert ids == [mine.pk]
    body = _text(response)
    for key in ("pending", "rejected"):
        player, _ = populated_game[key]
        assert player.nickname not in body
    assert game.title in body


# --------------------------------------------------------------------------
# 封禁账号的读权限
# --------------------------------------------------------------------------


def test_封禁账号不能读名单(api_client, populated_game):
    """封禁号写接口全被挡（IsAuthenticatedAndActive），读名单的口子不能更松。

    口径对齐 charactercards 的 `can_view_file`：
    「写接口挡住的封禁号，下发私密内容的口子不能更松」（architecture 14.3）。
    """
    game = populated_game["game"]
    banned, _ = populated_game["accepted"]
    banned.is_banned = True
    banned.save(update_fields=["is_banned"])

    api_client.force_authenticate(banned)
    assert api_client.get(f"/api/v1/games/{game.pk}/signups/").status_code in (401, 403)
    assert api_client.get(f"/api/v1/games/{game.pk}/roster/").status_code in (401, 403)


def test_注销账号不能读名单(api_client, populated_game):
    game = populated_game["game"]
    gone, _ = populated_game["accepted"]
    gone.is_deactivated = True
    gone.is_active = False
    gone.save(update_fields=["is_deactivated", "is_active"])

    api_client.force_authenticate(gone)
    assert api_client.get(f"/api/v1/games/{game.pk}/roster/").status_code in (401, 403)


def test_取消团后正式名单仍只给同团(api_client, populated_game, user_factory):
    game = populated_game["game"]
    services.cancel_game(game, reason="GM 跑路")
    api_client.force_authenticate(user_factory())
    assert api_client.get(f"/api/v1/games/{game.pk}/roster/").status_code == 403


def test_结团后正式名单仍只给同团(api_client, populated_game, user_factory):
    game = populated_game["game"]
    game.start_at = soon(hours=-1)
    game.card_deadline = soon(hours=-2)
    game.save(update_fields=["start_at", "card_deadline"])
    services.finish_game(game, attended_signup_ids=[populated_game["accepted"][1].pk])
    api_client.force_authenticate(user_factory())
    assert api_client.get(f"/api/v1/games/{game.pk}/roster/").status_code == 403
