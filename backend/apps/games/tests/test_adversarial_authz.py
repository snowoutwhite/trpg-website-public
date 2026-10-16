"""对抗测试：越权、质量赋值、CSRF、未登录状态码表。

攻击假设：
1. 非 GM / 别的团的 GM 能不能调 GM 端点（审批·代传卡·移除·扩容·开始·结团·取消·场次）？
2. GM 能不能拿本团 id + **别的团的 signup id** 去处置别人的报名？
3. PL 能不能用别人的 signup id 交卡 / 退出？能不能交**别人的卡**或撕掉的卡？
4. PATCH 团的时候塞 `gm` / `status` / `finished_at` 能不能直接改状态机？
5. 报名时 body 塞 `status=accepted` / `attended=true` 能不能质量赋值绕过？
6. 所有变更端点在没有 CSRF token 时会不会照样执行？
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.games import services
from apps.games.models import (
    GAME_RECRUITING,
    SIGNUP_ACCEPTED,
    SIGNUP_PENDING,
    Game,
    Session,
    Signup,
)

from .conftest import soon, upload

pytestmark = pytest.mark.django_db


# 所有 GM 侧写端点（路径模板 + body），用于批量越权扫描。
GM_GAME_ENDPOINTS = [
    ("expand/", {"max_players": 99}),
    ("start/", {}),
    ("finish/", {"attended_signup_ids": []}),
    ("cancel/", {"reason": "我说取消就取消"}),
    ("sessions/", {"index": 7, "label": "第 7 回"}),
]
GM_SIGNUP_ENDPOINTS = [
    ("review/", {"approved": True, "note": "放行"}),
    ("remove/", {"reason": "踢了"}),
    ("confirm-withdraw/", {"approved": True}),
]


@pytest.fixture
def victim(game_factory, user_factory, card_factory):
    """受害者团：GM + 一个已通过的 PL。"""
    game = game_factory(max_players=5)
    player = user_factory(nickname="受害PL")
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    game.refresh_from_db()
    record.refresh_from_db()
    return game, player, record


# --------------------------------------------------------------------------
# 1. 非 GM / 别的团 GM 调 GM 端点
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path,payload", GM_GAME_ENDPOINTS)
@pytest.mark.parametrize("attacker", ["plain", "other_gm", "team_member"])
def test_非本团GM调团级端点一律被拒(
    api_client, victim, user_factory, gm_factory, path, payload, attacker
):
    game, player, _ = victim
    actors = {"plain": user_factory, "other_gm": gm_factory, "team_member": lambda: player}
    api_client.force_authenticate(actors[attacker]())

    response = api_client.post(f"/api/v1/games/{game.pk}/{path}", payload, format="json")
    assert response.status_code not in (200, 201), f"{attacker} 用 {path} 得手了"
    assert response.json()["error"]["code"] in ("not_game_gm", "permission_denied")

    game.refresh_from_db()
    assert game.status == GAME_RECRUITING
    assert game.max_players == 5
    assert game.finished_at is None
    assert not game.cancel_reason
    assert Session.objects.filter(game=game).count() == 0


@pytest.mark.parametrize("path,payload", GM_SIGNUP_ENDPOINTS)
@pytest.mark.parametrize("attacker", ["plain", "other_gm", "team_member"])
def test_非本团GM调报名级端点一律被拒(
    api_client, victim, user_factory, gm_factory, path, payload, attacker
):
    game, player, record = victim
    actors = {"plain": user_factory, "other_gm": gm_factory, "team_member": lambda: player}
    api_client.force_authenticate(actors[attacker]())

    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/{path}", payload, format="json"
    )
    assert response.status_code not in (200, 201), f"{attacker} 用 {path} 得手了"
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED
    assert record.review_note == ""


def test_别的GM代传卡被拒(api_client, victim, gm_factory):
    game, _, record = victim
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/upload-card/",
        {"file": upload()},
        format="multipart",
    )
    assert response.status_code not in (200, 201)
    assert response.json()["error"]["code"] == "not_game_gm"


def test_别的GM不能PATCH我的团(api_client, victim, gm_factory):
    game, _, _ = victim
    api_client.force_authenticate(gm_factory())
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/", {"title": "我抢过来了"}, format="json"
    )
    assert response.status_code not in (200, 201)
    game.refresh_from_db()
    assert game.title != "我抢过来了"


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_别的GM不能改删我的场次(api_client, victim, gm_factory, method):
    game, _, _ = victim
    session = services.create_session(game, index=0, label="第 0 回")
    api_client.force_authenticate(gm_factory())
    call = getattr(api_client, method)
    path = f"/api/v1/games/{game.pk}/sessions/{session.pk}/"
    response = call(path, {"label": "改掉"}, format="json") if method == "patch" else call(path)
    assert response.status_code not in (200, 204)
    session.refresh_from_db()
    assert session.label == "第 0 回"
    assert Session.objects.filter(pk=session.pk).exists()


# --------------------------------------------------------------------------
# 2. 跨团对象引用（本团 id + 别团 signup id）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path,payload", GM_SIGNUP_ENDPOINTS)
def test_GM不能拿本团id处置别团的报名(api_client, victim, game_factory, path, payload):
    """URL 里团 id 是自己的、signup id 是别团的 —— 必须 404。"""
    victim_game, _, record = victim
    mine = game_factory(gm=victim_game.gm)  # 同一个 GM 名下的另一个团

    api_client.force_authenticate(victim_game.gm)
    response = api_client.post(
        f"/api/v1/games/{mine.pk}/signups/{record.pk}/{path}", payload, format="json"
    )
    assert response.status_code == 404
    record.refresh_from_db()
    assert record.status == SIGNUP_ACCEPTED


def test_GM代传卡不能指向别团的报名(api_client, victim, game_factory):
    victim_game, _, record = victim
    mine = game_factory(gm=victim_game.gm)
    api_client.force_authenticate(victim_game.gm)
    response = api_client.post(
        f"/api/v1/games/{mine.pk}/signups/{record.pk}/upload-card/",
        {"file": upload()},
        format="multipart",
    )
    assert response.status_code == 404
    record.refresh_from_db()
    assert record.card_uploaded_by_gm is False


def test_GM不能给不存在的报名代传卡(api_client, victim):
    game, _, _ = victim
    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/999999/upload-card/",
        {"file": upload()},
        format="multipart",
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# 3. PL 侧越权
# --------------------------------------------------------------------------


def test_PL没有报名不能交卡也不能退出(api_client, victim, user_factory, card_factory):
    """交卡/退出接口不收 signup id，只按「本团 + 本人」取记录；没报名就 404。"""
    game, _, _ = victim
    outsider = user_factory()
    api_client.force_authenticate(outsider)
    assert (
        api_client.post(
            f"/api/v1/games/{game.pk}/submit-card/",
            {"card_id": card_factory(outsider).pk},
            format="json",
        ).status_code
        == 404
    )
    assert api_client.post(f"/api/v1/games/{game.pk}/withdraw/", {}, format="json").status_code == 404


def test_交别人的卡与不存在的卡返回同一个码(api_client, game_factory, user_factory, card_factory):
    """别人的卡 id 必须与「根本不存在的 id」不可区分，否则能探测卡是否存在。"""
    game = game_factory()
    me = user_factory()
    other = user_factory()
    services.signup(game, me)
    victim_card = card_factory(other, is_public=False)

    api_client.force_authenticate(me)
    stolen = api_client.post(
        f"/api/v1/games/{game.pk}/submit-card/", {"card_id": victim_card.pk}, format="json"
    )
    ghost = api_client.post(
        f"/api/v1/games/{game.pk}/submit-card/", {"card_id": 987654}, format="json"
    )
    assert stolen.status_code == ghost.status_code == 404
    assert stolen.json() == ghost.json()
    assert Signup.objects.get(game=game, player=me).card_id is None


def test_交公开的别人的卡也不行(api_client, game_factory, user_factory, card_factory):
    game = game_factory()
    me = user_factory()
    other = user_factory()
    services.signup(game, me)
    api_client.force_authenticate(me)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/submit-card/",
        {"card_id": card_factory(other, is_public=True).pk},
        format="json",
    )
    assert response.status_code == 404


def test_交撕掉的卡被拒(api_client, game_factory, user_factory, card_factory):
    game = game_factory()
    me = user_factory()
    services.signup(game, me)
    card = card_factory(me)
    card.status = "torn"
    card.save(update_fields=["status"])

    api_client.force_authenticate(me)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/submit-card/", {"card_id": card.pk}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_not_usable"
    assert Signup.objects.get(game=game, player=me).status == SIGNUP_PENDING


def test_GM不能报自己的团(api_client, game_factory):
    game = game_factory()
    api_client.force_authenticate(game.gm)
    response = api_client.post(f"/api/v1/games/{game.pk}/signup/", {}, format="json")
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "cannot_signup_own_game"


# --------------------------------------------------------------------------
# 4 & 5. 质量赋值
# --------------------------------------------------------------------------


def test_PATCH团不能改gm与状态机字段(api_client, victim, user_factory):
    """`gm` / `status` / `finished_at` / `auto_closed` 都不在可写字段里。"""
    game, _, _ = victim
    thief = user_factory()
    api_client.force_authenticate(game.gm)
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/",
        {
            "gm": thief.pk,
            "status": "finished",
            "finished_at": soon(days=-1).isoformat(),
            "auto_closed": True,
            "cancel_reason": "偷偷取消",
            "title": "改个标题",
        },
        format="json",
    )
    assert response.status_code == 200
    game.refresh_from_db()
    assert game.gm_id != thief.pk
    assert game.status == GAME_RECRUITING
    assert game.finished_at is None
    assert game.auto_closed is False
    assert game.cancel_reason == ""
    assert game.title == "改个标题"  # 正向对照：允许改的确实改了


def test_报名body塞状态与到场不生效(api_client, game_factory, user_factory):
    game = game_factory(signup_mode="pool_review")
    player = user_factory()
    api_client.force_authenticate(player)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signup/",
        {"status": "accepted", "attended": True, "order": 0, "card": 1},
        format="json",
    )
    assert response.status_code == 201
    record = Signup.objects.get(game=game, player=player)
    assert record.status == SIGNUP_PENDING
    assert record.attended is False
    assert record.card_id is None


def test_放团body塞gm与状态不生效(api_client, gm_factory, user_factory):
    gm = gm_factory()
    victim_user = user_factory()
    api_client.force_authenticate(gm)
    response = api_client.post(
        "/api/v1/games/",
        {
            "title": "质量赋值团",
            "start_at": soon(days=3).isoformat(),
            "gm": victim_user.pk,
            "status": "finished",
            "finished_at": soon(days=-1).isoformat(),
            "auto_closed": True,
        },
        format="json",
    )
    assert response.status_code == 201
    game = Game.objects.get(title="质量赋值团")
    assert game.gm_id == gm.pk
    assert game.status == GAME_RECRUITING
    assert game.finished_at is None
    assert game.auto_closed is False


def test_普通用户不能放团(api_client, user_factory):
    api_client.force_authenticate(user_factory())
    response = api_client.post(
        "/api/v1/games/", {"title": "非GM团", "start_at": soon(days=3).isoformat()}, format="json"
    )
    assert response.status_code == 403  # W5 状态码统一：身份/角色/资格类拒绝 → 403
    assert response.json()["error"]["code"] == "not_gm"
    assert not Game.objects.filter(title="非GM团").exists()


def test_禁言的GM不能放团也不能报名(api_client, gm_factory, game_factory):
    gm = gm_factory()
    gm.is_muted = True
    gm.save(update_fields=["is_muted"])
    other_game = game_factory()

    api_client.force_authenticate(gm)
    assert (
        api_client.post(
            "/api/v1/games/", {"title": "禁言团", "start_at": soon(days=3).isoformat()},
            format="json",
        ).status_code
        == 403
    )
    assert api_client.post(f"/api/v1/games/{other_game.pk}/signup/", {}, format="json").status_code == 403
    assert Signup.objects.count() == 0


# --------------------------------------------------------------------------
# 6. CSRF
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path_tpl,payload",
    [
        ("post", "/api/v1/games/", {"title": "无 token 团", "start_at": None}),
        ("patch", "/api/v1/games/{game}/", {"title": "无 token 改名"}),
        ("post", "/api/v1/games/{game}/signup/", {}),
        ("post", "/api/v1/games/{game}/withdraw/", {}),
        ("post", "/api/v1/games/{game}/submit-card/", {"card_id": 1}),
        ("post", "/api/v1/games/{game}/expand/", {"max_players": 9}),
        ("post", "/api/v1/games/{game}/start/", {}),
        ("post", "/api/v1/games/{game}/finish/", {"attended_signup_ids": []}),
        ("post", "/api/v1/games/{game}/cancel/", {"reason": "x"}),
        ("post", "/api/v1/games/{game}/sessions/", {"index": 3}),
        ("post", "/api/v1/games/{game}/signups/{signup}/review/", {"approved": True}),
        ("post", "/api/v1/games/{game}/signups/{signup}/remove/", {"reason": "x"}),
        ("post", "/api/v1/games/{game}/signups/{signup}/confirm-withdraw/", {"approved": True}),
    ],
)
def test_所有变更端点缺CSRF一律403(victim, method, path_tpl, payload):
    game, _, record = victim
    body = dict(payload)
    if body.get("start_at", "keep") is None:
        body["start_at"] = soon(days=3).isoformat()

    client = APIClient(enforce_csrf_checks=True)
    assert client.login(email=game.gm.email, password="testpass1234")

    path = path_tpl.format(game=game.pk, signup=record.pk)
    response = getattr(client, method)(path, body, format="json")
    assert response.status_code == 403, f"{path} 在没有 CSRF token 时被执行了"

    game.refresh_from_db()
    record.refresh_from_db()
    assert game.status == GAME_RECRUITING
    assert record.status == SIGNUP_ACCEPTED
    assert not Game.objects.filter(title__startswith="无 token").exists()


def test_场次改删缺CSRF也被拒(victim):
    game, _, _ = victim
    session = services.create_session(game, index=0, label="第 0 回")
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(email=game.gm.email, password="testpass1234")
    path = f"/api/v1/games/{game.pk}/sessions/{session.pk}/"
    assert client.patch(path, {"label": "改"}, format="json").status_code == 403
    assert client.delete(path).status_code == 403
    assert Session.objects.filter(pk=session.pk, label="第 0 回").exists()


# --------------------------------------------------------------------------
# 未登录全路由状态码表（固化现状，防止以后有人把 AllowAny 抹到写端点上）
# --------------------------------------------------------------------------


def test_未登录全路由状态码表(api_client, victim):
    """W5 状态码统一：未登录访问需登录接口一律 401（原先被 DRF 降级成 403）。"""
    game, _, record = victim
    session = services.create_session(game, index=0)
    expected = {
        ("get", "/api/v1/games/"): 200,
        ("get", "/api/v1/games/tags/"): 200,
        ("get", f"/api/v1/games/{game.pk}/"): 200,
        ("get", f"/api/v1/games/{game.pk}/sessions/"): 200,
        ("get", f"/api/v1/games/{game.pk}/signups/"): 401,
        ("get", f"/api/v1/games/{game.pk}/roster/"): 401,
        ("get", "/api/v1/games/my-signups/"): 401,
        ("get", f"/api/v1/games/{game.pk}/sessions/{session.pk}/"): 401,
        ("post", "/api/v1/games/"): 401,
        ("patch", f"/api/v1/games/{game.pk}/"): 401,
        ("post", f"/api/v1/games/{game.pk}/signup/"): 401,
        ("post", f"/api/v1/games/{game.pk}/withdraw/"): 401,
        ("post", f"/api/v1/games/{game.pk}/submit-card/"): 401,
        ("post", f"/api/v1/games/{game.pk}/expand/"): 401,
        ("post", f"/api/v1/games/{game.pk}/start/"): 401,
        ("post", f"/api/v1/games/{game.pk}/finish/"): 401,
        ("post", f"/api/v1/games/{game.pk}/cancel/"): 401,
        ("post", f"/api/v1/games/{game.pk}/sessions/"): 401,
        ("post", f"/api/v1/games/{game.pk}/signups/{record.pk}/review/"): 401,
        ("post", f"/api/v1/games/{game.pk}/signups/{record.pk}/remove/"): 401,
        ("post", f"/api/v1/games/{game.pk}/signups/{record.pk}/upload-card/"): 401,
        ("post", f"/api/v1/games/{game.pk}/signups/{record.pk}/confirm-withdraw/"): 401,
    }
    actual = {}
    for (method, path), _ in expected.items():
        response = getattr(api_client, method)(path, {}, format="json")
        actual[(method, path)] = response.status_code
    assert actual == expected


def test_GM代传卡的卡名含RTL覆盖字符一律400(api_client, victim):
    """业务规则与安全约束。"""
    game, _, record = victim
    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/signups/{record.pk}/upload-card/",
        {"file": upload(), "name": "坏\u202e卡"},
        format="multipart",
    )
    assert response.status_code == 400, response.content
