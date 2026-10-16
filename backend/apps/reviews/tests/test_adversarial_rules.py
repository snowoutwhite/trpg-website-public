"""红队（W3 对抗测试）：越权、状态机、输入、后台与 CSRF。

覆盖 安全测试规则里点名的几类：
越权 / 状态机绕过 / 输入攻击 / CSRF 缺失 / 游客访问登录接口，
外加后台非超级用户绕过匿名遮蔽的三条路（列、搜索、URL 过滤）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone

from apps.games.models import (
    GAME_FINISHED,
    SIGNUP_ACCEPTED,
    SIGNUP_REJECTED,
    SIGNUP_WITHDRAWN,
    Signup,
)
from apps.reviews.models import Review
from apps.reviews.services import REVIEW_TEXT_MAX_LENGTH
from apps.reviews.tests.conftest import (
    GIVEN_URL,
    PENDING_URL,
    QUOTA_URL,
    RECEIVED_URL,
    REVIEWS_URL,
    mutual_url,
)

pytestmark = pytest.mark.django_db

ADMIN_CHANGELIST = f"/{settings.ADMIN_URL}reviews/review/"


# --------------------------------------------------------------------------
# 1. 客户端伪造字段
# --------------------------------------------------------------------------


def test_客户端不能伪造被评者身份与评价人(gm_factory, user_factory, game_factory, api_client):
    """`reviewee_role` 必须由服务端按团内身份判定，`reviewer` 必须等于登录者。"""
    gm = gm_factory()
    attacker = user_factory()
    victim = user_factory()
    game = game_factory(gm, [attacker, victim])

    api_client.force_authenticate(attacker)
    response = api_client.post(
        REVIEWS_URL,
        {
            "game": game.pk,
            "reviewee": victim.pk,
            "verdict": "like",
            "text": "伪造试试",
            # 下面三个都是攻击载荷：想把 PL 评价塞进对方的 GM 卡，或把锅扣给别人。
            "reviewee_role": "gm",
            "reviewer": gm.pk,
            "id": 999,
        },
        format="json",
    )
    assert response.status_code == 201
    row = Review.objects.get(game=game, reviewee=victim)
    assert row.reviewee_role == "pl", "客户端把 reviewee_role 伪造成了 gm"
    assert row.reviewer_id == attacker.pk, "客户端把 reviewer 换成了别人"
    assert row.pk != 999


def test_评GM时身份由服务端判成gm(gm_factory, user_factory, game_factory, api_client):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    api_client.force_authenticate(player)
    api_client.post(
        REVIEWS_URL,
        {"game": game.pk, "reviewee": gm.pk, "verdict": "like", "text": "好 GM", "reviewee_role": "pl"},
        format="json",
    )
    assert Review.objects.get(game=game, reviewee=gm).reviewee_role == "gm"


# --------------------------------------------------------------------------
# 2. 越权与状态机
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [SIGNUP_REJECTED, SIGNUP_WITHDRAWN])
def test_被拒与退出的报名既不能评也不能被评(
    gm_factory, user_factory, game_factory, submit, status
):
    gm = gm_factory()
    player = user_factory()
    outsider = user_factory()
    game = game_factory(gm, [player])
    Signup.objects.create(game=game, player=outsider, order=9, status=status, attended=True)

    assert submit(outsider, game, player).json()["error"]["code"] == "not_attendee"
    assert submit(gm, game, outsider).json()["error"]["code"] == "invalid_review_target"


def test_accepted但没到场同样不算(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    absent = user_factory()
    present = user_factory()
    game = game_factory(gm, [absent, present], attended=[present])
    assert submit(absent, game, present).json()["error"]["code"] == "not_attendee"
    assert submit(present, game, absent).json()["error"]["code"] == "invalid_review_target"


def test_跨团被评者被拒(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    other_team_player = user_factory()
    game_a = game_factory(gm, [player])
    game_factory(gm, [other_team_player])
    assert submit(player, game_a, other_team_player).json()["error"]["code"] == "invalid_review_target"


def test_GM不能评自己也不能被自己评(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    assert submit(gm, game, gm).json()["error"]["code"] == "cannot_review_self"
    assert Review.objects.count() == 0


def test_改档后统计与档位保持一致(gm_factory, user_factory, game_factory, submit, pass_delay):
    """upsert 改 verdict 时若只加不减，赞倒赞会双记。

    W5 起统计只计「已对被评者可见」的评价，所以先让被评者跨过延迟锁，
    否则卡片上永远是 0，这条用例就测不到「双记」这件事了。
    """
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    pass_delay(player, game.finished_at)
    submit(gm, game, player, verdict="like", text="先赞")
    submit(gm, game, player, verdict="dislike", text="改成倒赞")

    player.player_card.refresh_from_db()
    card = player.player_card
    assert (card.likes, card.dislikes, card.reviews_received) == (0, 1, 1)
    assert Review.objects.filter(game=game, reviewee=player).count() == 1


def test_后台删除评价后重算被评者的卡(gm_factory, user_factory, game_factory, submit, pass_delay):
    from django.contrib import admin as django_admin

    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    pass_delay(player, game.finished_at)  # W5：统计只计已过延迟的评价
    submit(gm, game, player, verdict="like", text="待删")
    player.player_card.refresh_from_db()
    assert player.player_card.likes == 1

    review_admin = django_admin.site._registry[Review]
    review_admin.delete_model(None, Review.objects.get())
    player.player_card.refresh_from_db()
    assert (player.player_card.likes, player.player_card.reviews_received) == (0, 0)


def test_关闭赞功能后数据只隐藏不删(
    gm_factory, user_factory, game_factory, submit, api_client, site_config, pass_delay
):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player], mutual_review=True)
    submit(gm, game, player, verdict="like", text="关功能前写的")
    pass_delay(player, game.finished_at)

    site_config.like_feature_enabled = False
    site_config.save()

    api_client.force_authenticate(player)
    assert api_client.get(RECEIVED_URL).json()["results"] == []
    assert api_client.get(GIVEN_URL).json()["results"] == []
    assert api_client.get(PENDING_URL).status_code == 403
    assert api_client.get(mutual_url(game)).status_code == 403
    assert api_client.post(
        REVIEWS_URL, {"game": game.pk, "reviewee": gm.pk, "verdict": "like", "text": "x"},
        format="json",
    ).status_code == 403
    # 行还在，档位不公布
    assert Review.objects.count() == 1
    player.player_card.refresh_from_db()
    assert player.player_card.level == ""


# --------------------------------------------------------------------------
# 3. 输入攻击
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"game": "abc"},
        {"game": -1},
        {"game": 10**18},
        {"game": None},
        {"reviewee": "abc"},
        {"reviewee": -1},
        {"reviewee": 10**18},
        {"reviewee": [1, 2]},
        {"verdict": "neutral"},
        {"verdict": ["like"]},
        {"verdict": None},
    ],
)
def test_畸形入参一律400而不是500(gm_factory, user_factory, game_factory, api_client, payload):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    body = {"game": game.pk, "reviewee": player.pk, "verdict": "like", "text": "正常"}
    body.update(payload)
    api_client.force_authenticate(gm)
    response = api_client.post(REVIEWS_URL, body, format="json")
    assert response.status_code == 400, response.content
    assert response.json()["error"]["code"] in {"validation_error", "bad_request"}


def test_评价正文有长度上限(gm_factory, user_factory, game_factory, submit):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    assert submit(gm, game, player, text="字" * REVIEW_TEXT_MAX_LENGTH).status_code == 201
    over = submit(gm, game, player, text="字" * (REVIEW_TEXT_MAX_LENGTH + 1))
    assert over.status_code == 400


def test_正文里的NUL被挡在400而不是把生产库打成500(gm_factory, user_factory, game_factory, submit):
    """PostgreSQL 存不下 NUL，一路放到 ORM 就是 500；DRF CharField 的
    `ProhibitNullCharactersValidator` 已经在序列化层拦住，这里钉住这个行为。
    """
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    response = submit(gm, game, player, text="正常\x00内容")
    assert response.status_code == 400
    assert Review.objects.count() == 0


def test_其余控制字符与双向覆盖字符按原样存储(gm_factory, user_factory, game_factory, submit):
    """简报口径「存储即可，但长度要有上限」：后端只保证原样存 + 有上限，

    转义是前端渲染的责任。留这条用例是为了让「哪些字符进得来」有据可查：
    C0 控制符与 U+200B/U+202E 目前进得来（报告里作为对前端层的建议）。
    """
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    dirty = "控制\x07符\x1b零宽​双向‮覆盖\n换行\t制表"
    assert submit(gm, game, player, text=dirty).status_code == 201
    assert Review.objects.get().text == dirty


def test_HTML与Markdown载荷原样存储不被解释(gm_factory, user_factory, game_factory, submit):
    """存储型 XSS 的防线在前端渲染，后端只保证「原样存、有上限、不被当成结构」。"""
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    payload = '<script>alert(1)</script><img src=x onerror=alert(2)>[x](javascript:alert(3))'
    assert submit(gm, game, player, text=payload).status_code == 201
    assert Review.objects.get().text == payload


# --------------------------------------------------------------------------
# 4. 后台：非超级用户不得看到评价人
# --------------------------------------------------------------------------


@pytest.fixture
def staff_client(db, user_factory, gm_factory, game_factory, submit):
    """一个只有查看/删除权限的非超级 staff，和一条已经存在的评价。"""
    gm = gm_factory(nickname="后台评价人MMM")
    player = user_factory(nickname="后台被评者NNN")
    game = game_factory(gm, [player])
    submit(gm, game, player, text="后台用例正文")

    staff = user_factory(nickname="工作人员SSS", is_staff=True)
    staff.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="reviews", codename__in=["view_review", "delete_review"]
        )
    )
    client = Client()
    client.force_login(staff)
    return client, gm, player


def test_后台非超级用户的列表不含评价人且搜索搜不到(staff_client):
    client, reviewer, _ = staff_client
    page = client.get(ADMIN_CHANGELIST)
    assert page.status_code == 200
    body = page.content.decode()
    assert "后台评价人MMM" not in body, "changelist 把评价人昵称印出来了"
    assert "后台被评者NNN" in body

    searched = client.get(ADMIN_CHANGELIST, {"q": "后台评价人MMM"})
    assert searched.status_code == 200
    assert "后台用例正文" not in searched.content.decode(), "搜索项把评价人昵称也搜了"


def test_后台非超级用户不能用URL参数按评价人过滤(staff_client):
    client, reviewer, _ = staff_client
    for query in (
        {"reviewer__id__exact": reviewer.pk},
        {"reviewer__nickname": "后台评价人MMM"},
        {"reviewer": reviewer.pk},
    ):
        response = client.get(ADMIN_CHANGELIST, query)
        assert response.status_code == 400, f"{query} 没被挡住（返回 {response.status_code}）"


def test_后台非超级用户的详情页与排序都不暴露评价人(staff_client):
    client, reviewer, _ = staff_client
    review = Review.objects.get()
    detail = client.get(f"{ADMIN_CHANGELIST}{review.pk}/change/")
    assert detail.status_code == 200
    assert "后台评价人MMM" not in detail.content.decode()
    # 排序参数只能指向 list_display 里的列，评价人列根本不存在。
    for order in ("0", "-1", "1.2.3"):
        assert client.get(ADMIN_CHANGELIST, {"o": order}).status_code == 200


def test_后台对象描述不带评价人(gm_factory, user_factory, game_factory, submit):
    """`__str__` 会进 LogEntry 与删除确认页。"""
    gm = gm_factory(nickname="str评价人")
    player = user_factory(nickname="str被评者")
    game = game_factory(gm, [player])
    submit(gm, game, player)
    assert "str评价人" not in str(Review.objects.get())


# --------------------------------------------------------------------------
# 5. 未登录 / CSRF
# --------------------------------------------------------------------------


def test_未登录全路由状态码表(api_client, gm_factory, user_factory, game_factory):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    cases = [
        ("get", PENDING_URL),
        ("get", QUOTA_URL),
        ("get", GIVEN_URL),
        ("get", RECEIVED_URL),
        ("get", mutual_url(game)),
    ]
    for method, url in cases:
        response = getattr(api_client, method)(url)
        assert response.status_code in (401, 403), f"{url} → {response.status_code}"
        assert response.json()["error"]["code"] in {"not_authenticated", "permission_denied"}

    post = api_client.post(
        REVIEWS_URL, {"game": game.pk, "reviewee": player.pk, "verdict": "like", "text": "x"},
        format="json",
    )
    assert post.status_code in (401, 403)
    assert Review.objects.count() == 0


def test_会话登录后提交评价仍需CSRF令牌(gm_factory, user_factory, game_factory):
    from rest_framework.test import APIClient

    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])

    client = APIClient(enforce_csrf_checks=True)
    client.force_login(gm)
    response = client.post(
        REVIEWS_URL,
        {"game": game.pk, "reviewee": player.pk, "verdict": "like", "text": "无令牌"},
        format="json",
    )
    assert response.status_code == 403, "缺 CSRF 令牌也能写入"
    assert "CSRF" in response.json()["error"]["message"], "403 不是 CSRF 挡的，用例失效"
    assert Review.objects.count() == 0


def test_只读接口不接受写方法(api_client, gm_factory, user_factory, game_factory):
    gm = gm_factory()
    player = user_factory()
    game = game_factory(gm, [player])
    api_client.force_authenticate(player)
    for url in (PENDING_URL, QUOTA_URL, GIVEN_URL, RECEIVED_URL, mutual_url(game)):
        assert api_client.post(url, {}, format="json").status_code == 405, url
        assert api_client.delete(url).status_code == 405, url
    # 评价不可撤回：写入入口没有 DELETE / PUT / PATCH。
    for method in ("delete", "put", "patch"):
        assert getattr(api_client, method)(REVIEWS_URL).status_code == 405


def test_窗口关闭后既不能改也不能删(gm_factory, user_factory, game_factory, submit, site_config):
    gm = gm_factory()
    player = user_factory()
    window = timedelta(days=site_config.review_window_days)
    game = game_factory(gm, [player], finished_at=timezone.now() - window + timedelta(seconds=5))
    assert submit(gm, game, player, text="窗口内").status_code == 201

    game.finished_at = timezone.now() - window - timedelta(seconds=5)
    game.status = GAME_FINISHED
    game.save(update_fields=["finished_at", "status"])
    assert submit(gm, game, player, text="窗口外改写").json()["error"]["code"] == "review_window_closed"
    assert Review.objects.get().text == "窗口内"


def test_配额不会因为重复提交被算多(gm_factory, user_factory, game_factory, submit, api_client):
    gm = gm_factory()
    players = [user_factory() for _ in range(3)]
    game = game_factory(gm, players)
    for player in players:
        submit(gm, game, player, text="第一次")
        submit(gm, game, player, text="改一次")

    api_client.force_authenticate(gm)
    quota = api_client.get(QUOTA_URL).json()
    assert quota == {"quota": 3, "used": 3, "remaining": 0, "like_feature_enabled": True}


def test_未到场PL不进配额分母(gm_factory, user_factory, game_factory, api_client):
    gm = gm_factory()
    present = user_factory()
    absent = user_factory()
    game_factory(gm, [present, absent], attended=[present])
    api_client.force_authenticate(gm)
    assert api_client.get(QUOTA_URL).json()["quota"] == 1


def test_报名状态非accepted的人不进配额(gm_factory, user_factory, game_factory, api_client):
    gm = gm_factory()
    player = user_factory()
    ghost = user_factory()
    game = game_factory(gm, [player])
    Signup.objects.create(
        game=game, player=ghost, order=8, status=SIGNUP_WITHDRAWN, attended=True
    )
    Signup.objects.filter(game=game, player=player).update(status=SIGNUP_ACCEPTED, attended=True)
    api_client.force_authenticate(gm)
    assert api_client.get(QUOTA_URL).json()["quota"] == 1


def test_窗口提醒通知不含任何评价人线索(
    gm_factory, user_factory, game_factory, submit, site_config
):
    """唯一一条与评价相关的站内信：只许有团名、截止时间、自己还差几个没评。"""
    from apps.notifications.models import Notification
    from apps.reviews.services import WINDOW_CLOSING_LEAD, run_window_closing_cycle

    gm = gm_factory(nickname="提醒评价人PPP")
    player = user_factory(nickname="提醒被评者QQQ")
    window = timedelta(days=site_config.review_window_days)
    game = game_factory(
        gm, [player], finished_at=timezone.now() - window + WINDOW_CLOSING_LEAD - timedelta(hours=1)
    )
    submit(gm, game, player, text="GM 已经评过了")

    assert run_window_closing_cycle()["notified"] == 1  # 只剩 PL 没评
    notice = Notification.objects.get(recipient=player)
    assert notice.actor_id is None, "通知带上了 actor，等于把人交出去"
    assert set(notice.payload) == {"game_title", "ends_at", "pending"}
    assert "提醒评价人PPP" not in str(notice.payload)
    # GM 已经评完了，不该收到提醒（否则「谁还没评」就反着泄露了）。
    assert not Notification.objects.filter(recipient=gm, event=notice.event).exists()


@pytest.mark.parametrize("game_id", ["0", "99999999", "9" * 30])
def test_不存在或超大的团id不打出500(api_client, user_factory, game_id):
    api_client.force_authenticate(user_factory())
    response = api_client.get(f"/api/v1/reviews/games/{game_id}/mutual/")
    assert response.status_code < 500, response.content
