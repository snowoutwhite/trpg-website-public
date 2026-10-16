"""封禁 / 注销账号在**真实 cookie 会话**下的口径。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ALLAUTH = "/_allauth/browser/v1"
ME = "/api/v1/accounts/me/"
NOTIFICATIONS = "/api/v1/notifications/"
MARK_READ = "/api/v1/notifications/read/"
ADMIN_ANNOUNCEMENTS = "/api/v1/home/admin/announcements/"


def _login(client: APIClient, email: str, password: str = "testpass1234"):
    return client.post(
        f"{ALLAUTH}/auth/login", {"email": email, "password": password}, format="json"
    )


def _code(response) -> str:
    body = response.json()
    return body.get("error", {}).get("code", "")


def _logged_in_client(user_factory, **extra):
    """造一个**真的登录过**（带 sessionid cookie）的客户端。"""
    email = extra.pop("email", None) or f"real-{id(extra)}@example.com"
    user = user_factory(email=email, **extra)
    client = APIClient()
    assert _login(client, email).status_code == 200, "前置条件：封禁前必须登得进去"
    assert client.cookies.get("sessionid"), "前置条件：登录后应有 sessionid cookie"
    assert client.get(ME).status_code == 200, "前置条件：封禁前读接口应当 200"
    return user, client


# --------------------------------------------------------------------------
# 封禁：真实会话下读写一律 403 + account_banned
# --------------------------------------------------------------------------


def test_封禁后真实会话的写接口是403加account_banned(user_factory):
    from apps.accounts.services import ban_user

    user, client = _logged_in_client(user_factory, nickname="真会话封禁写", email="rs-w@example.com")
    ban_user(user, reason="违规")

    response = client.post(MARK_READ, {}, format="json")
    assert response.status_code == 403, f"真实会话下封禁号的写接口回了 {response.status_code}"
    assert _code(response) == "account_banned", response.json()


def test_封禁后真实会话的读接口也是403加account_banned(user_factory):
    """读接口不能把封禁号当成正常登录用户 —— 否则「封禁」只封住了写。"""
    from apps.accounts.services import ban_user

    user, client = _logged_in_client(user_factory, nickname="真会话封禁读", email="rs-r@example.com")
    ban_user(user, reason="违规")

    wrong = {}
    for url in (ME, NOTIFICATIONS, "/api/v1/charactercards/mine/", "/api/v1/gallery/reports/mine/"):
        response = client.get(url)
        if response.status_code != 403 or _code(response) != "account_banned":
            wrong[url] = (response.status_code, response.content[:200])
    assert not wrong, f"以下读接口对封禁号不是 403/account_banned：{wrong}"


def test_先封禁再拿旧cookie访问同样是403(user_factory):
    """封禁发生在两次请求之间：手上那张 cookie 不会变，服务端必须当场改口径。"""
    from apps.accounts.services import ban_user

    user, client = _logged_in_client(user_factory, nickname="旧cookie", email="rs-c@example.com")
    cookie_before = client.cookies["sessionid"].value
    ban_user(user, reason="违规")

    response = client.get(ME)
    assert client.cookies["sessionid"].value == cookie_before, "用例前提：cookie 没被换掉"
    assert response.status_code == 403
    assert _code(response) == "account_banned"


def test_解封后同一个会话恢复正常(user_factory):
    """反向保险：上面的 403 不能是「反正都失败」。"""
    from apps.accounts.services import ban_user, unban_user

    user, client = _logged_in_client(user_factory, nickname="解封", email="rs-u@example.com")
    ban_user(user, reason="误封")
    assert client.get(ME).status_code == 403
    unban_user(user)
    assert client.get(ME).status_code == 200, "解封后旧会话应当恢复可用"


def test_封禁的staff访问站长写接口也是403加account_banned(user_factory):
    """站主被封禁：`IsSiteStaff` 继承自 `IsAuthenticatedAndActive`，
    账号状态那一格必须先于 `is_staff` 生效，否则封禁对站主等于没封。"""
    from apps.accounts.services import ban_user

    user, client = _logged_in_client(
        user_factory, nickname="封禁站主", email="rs-s@example.com", is_staff=True
    )
    assert client.get(ADMIN_ANNOUNCEMENTS).status_code == 200, "前置条件：封禁前站主读得到"
    ban_user(user, reason="违规")

    response = client.post(ADMIN_ANNOUNCEMENTS, {"title": "x", "body": "y"}, format="json")
    assert response.status_code == 403, response.status_code
    assert _code(response) == "account_banned", response.json()


# --------------------------------------------------------------------------
# 注销 / 停用：同一条路，code 是 account_deactivated
# --------------------------------------------------------------------------


def test_后台取消账号可用后真实会话是403加account_deactivated(user_factory):
    """站主在后台把「账号可用」取消（`is_active=False`，不是封禁）——
    密码没动，会话不会被挤掉，于是这是注销态真实会话最常见的来路。"""
    user, client = _logged_in_client(user_factory, nickname="停用", email="rs-d@example.com")
    user.is_active = False
    user.save(update_fields=["is_active"])

    for url, method, payload in ((ME, "get", None), (MARK_READ, "post", {})):
        response = (
            client.get(url) if method == "get" else client.post(url, payload, format="json")
        )
        assert response.status_code == 403, f"{method} {url} → {response.status_code}"
        assert _code(response) == "account_deactivated", response.json()


def test_注销后再持有会话也是403加account_deactivated(user_factory):
    """自助注销会改密码（`set_unusable_password`）从而挤掉所有旧会话，
    所以这里用 `force_login` 复现「注销态账号手上有一张有效会话」的那一格。"""
    from apps.accounts.services import deactivate_account

    user = user_factory(nickname="注销", email="rs-x@example.com")
    deactivate_account(user)
    client = APIClient()
    client.force_login(user)

    response = client.get(ME)
    assert response.status_code == 403, response.status_code
    assert _code(response) == "account_deactivated", response.json()


def test_封禁且注销时code仍是封禁(user_factory):
    """两个状态同时为真时的优先级必须与 `IsAuthenticatedAndActive` 一致：先封禁。"""
    user = user_factory(nickname="双状态", email="rs-b2@example.com")
    user.is_banned = True
    user.is_active = False
    user.is_deactivated = True
    user.save(update_fields=["is_banned", "is_active", "is_deactivated"])
    client = APIClient()
    client.force_login(user)

    response = client.get(ME)
    assert response.status_code == 403
    assert _code(response) == "account_banned", response.json()


def test_自助注销会立刻挤掉自己的会话(user_factory):
    """回归保险：让会话取得回封禁号之后，注销接口原本的「当场登出」不能退化。"""
    _, client = _logged_in_client(user_factory, nickname="自助注销", email="rs-self@example.com")
    assert client.post("/api/v1/accounts/me/deactivate/", {}, format="json").status_code == 200
    assert client.get(ME).status_code == 401, "注销后自己的会话应当彻底失效（游客）"


# --------------------------------------------------------------------------
# 不能退的底线
# --------------------------------------------------------------------------


def test_封禁号登不进来(user_factory):
    from apps.accounts.services import ban_user

    user = user_factory(nickname="登不进", email="rs-l@example.com")
    ban_user(user, reason="违规")

    fresh = APIClient()
    response = _login(fresh, "rs-l@example.com")
    assert response.status_code != 200, f"封禁号登进来了：{response.status_code} {response.content[:200]}"
    assert fresh.get(ME).status_code == 401


def test_注销号登不进来(user_factory):
    from apps.accounts.services import deactivate_account

    user = user_factory(nickname="注销登不进", email="rs-l2@example.com")
    deactivate_account(user)

    fresh = APIClient()
    assert _login(fresh, "rs-l2@example.com").status_code != 200
    assert fresh.get(ME).status_code == 401


def test_游客仍然是401不是403(user_factory):
    """分界线不能被本次改动抹平：没登录就是 401。"""
    guest = APIClient()
    response = guest.get(ME)
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


def test_封禁的staff进不了django后台(client, user_factory):
    """后台闸是 `AdminSite.has_permission`（`is_active and is_staff`）——
    认证后端放行会话取回之后，这道闸必须仍然拦得住。"""
    from apps.accounts.services import ban_user

    user = user_factory(nickname="后台站主", email="rs-adm@example.com", is_staff=True)
    admin_url = "/" + settings.ADMIN_URL
    assert client.login(email="rs-adm@example.com", password="testpass1234")
    assert client.get(admin_url, follow=True).status_code == 200

    ban_user(user, reason="违规")
    response = client.get(admin_url, follow=False)
    assert response.status_code == 302, f"封禁站主仍然进得了后台：{response.status_code}"
    assert "login" in response["Location"], response["Location"]


def test_allauth会话接口对封禁会话不多说一个字(user_factory):
    """④ 如实记录 `GET /_allauth/browser/v1/auth/session` 的返回。

    口径：封禁会话在 allauth 眼里**不算已认证**（返回 401 的未认证信封），
    响应体里不得出现邮箱、封禁理由这类多余信息。
    """
    from apps.accounts.services import ban_user

    user, client = _logged_in_client(user_factory, nickname="会话接口", email="rs-sess@example.com")
    ban_user(user, reason="内部备注不该外露")

    response = client.get(f"{ALLAUTH}/auth/session")
    body = response.content.decode()
    assert "内部备注不该外露" not in body, "封禁理由外露了"
    assert response.status_code == 401, f"allauth 会话接口回了 {response.status_code}：{body[:300]}"


def test_封禁号仍然能把自己的会话登出(user_factory):
    """封禁号在 allauth 眼里是游客，但登出必须照样有效 ——
    否则手里那张 403 会话要挂 30 天（`SESSION_COOKIE_AGE`）才自然过期。"""
    from apps.accounts.services import ban_user

    user, client = _logged_in_client(user_factory, nickname="登出", email="rs-out@example.com")
    ban_user(user, reason="违规")

    client.delete(f"{ALLAUTH}/auth/session")
    response = client.get(ME)
    assert response.status_code == 401, "登出后仍被当成封禁会话，说明 session 没被清掉"
    assert _code(response) == "not_authenticated"


def test_公开读接口上封禁号不得比游客看得多(user_factory, site_config):
    """② 的另一半：`AllowAny` 的接口走不到权限类。

    认证后端现在会把封禁号取回来，于是 `request.user.is_authenticated` 为真 ——
    可见性函数如果只判这一个条件，被封禁的人就能继续读「同团可见」的内容。
    口径：**公开读接口上，封禁 / 停用的会话按游客算。**
    """
    from apps.accounts.services import ban_user
    from apps.games import services as game_services
    from apps.reports import services as report_services

    gm = user_factory(nickname="同团GM", email="rs-pg@example.com", is_gm=True)
    member = user_factory(nickname="同团PL", email="rs-pp@example.com")
    game = game_services.create_game(
        gm,
        title="同团可见团",
        rule_system="COC",
        start_at=timezone.now() + timedelta(hours=1),
        min_players=1,
        max_players=5,
        requires_card=False,
    )
    signup = game_services.signup(game, member)
    game_services.start_game(game)
    game_services.finish_game(game, attended_signup_ids=[signup.pk])
    report, _ = report_services.submit_report(
        gm, game, title="同团战报", body_markdown="正文", visibility="same_game"
    )

    client = APIClient()
    assert _login(client, "rs-pp@example.com").status_code == 200
    detail = f"/api/v1/reports/{report.pk}/"
    assert client.get(detail).status_code == 200, "前置条件：封禁前同团成员看得见"

    ban_user(member, reason="违规")
    assert client.get(detail).status_code == 404, "封禁号还能读同团可见的战报"
    assert APIClient().get(detail).status_code == 404, "对照：游客本来就看不见"


def test_忘写权限类的新视图默认也对账号状态把关(user_factory, rf):
    """② 的兜底：DRF 的 `DEFAULT_PERMISSION_CLASSES` 必须是带账号状态的那一个。

    现存视图全都显式写了 `permission_classes`，所以这条只有在**将来新增视图
    忘了写**时才生效 —— 正因为如此，它只能用一条断言钉住，不能靠跑接口测出来。
    """
    from rest_framework.settings import api_settings

    from common.permissions import IsAuthenticatedAndActive

    assert api_settings.DEFAULT_PERMISSION_CLASSES == [IsAuthenticatedAndActive]


def test_封禁号动不了allauth的账户管理接口(user_factory):
    """封禁不能只封住 DRF 那一侧：改密码 / 改邮箱走的是 allauth headless，
    它只看 `request.user.is_authenticated`，让会话取得回用户之后这里会敞开。"""
    from apps.accounts.services import ban_user

    user, client = _logged_in_client(user_factory, nickname="allauth写", email="rs-aa@example.com")
    ban_user(user, reason="违规")

    wrong = {}
    for method, path, payload in (
        ("get", f"{ALLAUTH}/account/email", {}),
        ("post", f"{ALLAUTH}/account/email", {"email": "new-aa@example.com"}),
        (
            "post",
            f"{ALLAUTH}/account/password/change",
            {"current_password": "testpass1234", "new_password": "brandnewpass9876"},
        ),
    ):
        response = getattr(client, method)(path, payload, format="json")
        if response.status_code not in (401, 403, 409):
            wrong[(method, path)] = response.status_code
    assert not wrong, f"封禁号还能用 allauth 账户管理接口：{wrong}"
