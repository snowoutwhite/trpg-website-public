"""封禁号登录明示提示与它不能打开的枚举通道。"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ALLAUTH = "/_allauth/browser/v1"
LOGIN = f"{ALLAUTH}/auth/login"
SESSION = f"{ALLAUTH}/auth/session"
ME = "/api/v1/accounts/me/"
NOTIFICATIONS = "/api/v1/notifications/"
MARK_READ = "/api/v1/notifications/read/"
PASSWORD = "testpass1234"


def _login(client: APIClient, email: str, password: str = PASSWORD):
    return client.post(LOGIN, {"email": email, "password": password}, format="json")


def _banned(user_factory, email: str):
    from apps.accounts.services import ban_user

    user = user_factory(email=email)
    ban_user(user, reason="站主写的封禁理由-不应外泄")
    return user


# ① 封禁号 + 正确密码 → 403 account_banned，不带邮箱与封禁理由
def test_封禁号正确密码回403加account_banned(user_factory):
    _banned(user_factory, "ban-ok@example.com")
    response = _login(APIClient(), "ban-ok@example.com")

    assert response.status_code == 403, response.content[:300]
    body = response.json()
    assert body["status"] == 403
    assert [e["code"] for e in body["errors"]] == ["account_banned"], body
    assert body["errors"][0]["message"], "要带一句人话"
    raw = response.content.decode()
    assert "ban-ok@example.com" not in raw, "响应里出现了邮箱"
    assert "站主写的封禁理由" not in raw, "封禁理由不对外（与现有 403 account_banned 口径一致）"
    assert "data" not in body, "不应带 user / flows 之类的会话数据"


# ② 封禁号 + 错误密码 ≡ 普通号 + 错误密码（逐字段）
def test_封禁号错误密码与普通号错误密码响应逐字段一致(user_factory):
    _banned(user_factory, "ban-wrong@example.com")
    user_factory(email="normal-wrong@example.com")

    banned = _login(APIClient(), "ban-wrong@example.com", "not-the-password")
    normal = _login(APIClient(), "normal-wrong@example.com", "not-the-password")

    assert banned.status_code == normal.status_code == 400
    assert banned.json() == normal.json()
    assert banned.json()["errors"][0]["code"] == "email_password_mismatch"


# ③ 不存在的邮箱 ≡ ②
def test_不存在邮箱与封禁号错误密码响应逐字段一致(user_factory):
    _banned(user_factory, "ban-wrong2@example.com")

    banned = _login(APIClient(), "ban-wrong2@example.com", "not-the-password")
    ghost = _login(APIClient(), "nobody-here@example.com", "not-the-password")

    assert banned.status_code == ghost.status_code == 400
    assert banned.json() == ghost.json()


# ④ 正常号正确密码不受影响
def test_正常号正确密码照常登录(user_factory):
    user_factory(email="fine@example.com")
    client = APIClient()
    response = _login(client, "fine@example.com")

    assert response.status_code == 200, response.content[:300]
    assert response.json()["meta"]["is_authenticated"] is True
    assert client.get(ME).status_code == 200


# ⑤ 注销（未封禁）账号正确密码 → 维持现状：不是 200，也不是 account_banned
def test_注销号正确密码维持原状(user_factory):
    from apps.accounts.services import deactivate_account

    user = user_factory(email="gone@example.com")
    deactivate_account(user)
    client = APIClient()
    response = _login(client, "gone@example.com")

    assert response.status_code != 200
    assert "account_banned" not in response.content.decode()
    assert client.get(ME).status_code == 401


def test_注销号正确密码与错误密码响应一致(user_factory):
    """注销号本来就不区分密码对错（维持现状）；钉住它，免得本次放行把它也带出来。"""
    from apps.accounts.services import deactivate_account

    user = user_factory(email="gone2@example.com")
    deactivate_account(user)
    right = _login(APIClient(), "gone2@example.com")
    wrong = _login(APIClient(), "gone2@example.com", "not-the-password")
    assert right.status_code == wrong.status_code
    assert right.json() == wrong.json()


# ⑥ 封禁号尝试登录后 session 探测仍是 401 游客
def test_封禁号登录尝试后session探测仍是401游客(user_factory):
    _banned(user_factory, "ban-probe@example.com")
    client = APIClient()
    assert _login(client, "ban-probe@example.com").status_code == 403

    probe = client.get(SESSION)
    assert probe.status_code == 401
    body = probe.json()
    assert body["meta"]["is_authenticated"] is False
    assert "user" not in body.get("data", {})
    assert "methods" not in body.get("data", {})


# ⑦ 封禁号尝试登录后不存在任何可用登录态
def test_封禁号登录尝试后需登录接口仍拒绝(user_factory):
    _banned(user_factory, "ban-noauth@example.com")
    client = APIClient()
    assert _login(client, "ban-noauth@example.com").status_code == 403

    assert "_auth_user_id" not in client.session
    assert client.get(ME).status_code == 401
    assert client.get(NOTIFICATIONS).status_code == 401
    assert client.post(MARK_READ, {}, format="json").status_code in (401, 403)


def test_封禁号登录尝试不留认证记录给同浏览器后来的登录(user_factory):
    """allauth 在 pre_login 之前就记了一条「password 认证」到 session；
    同一浏览器随后换正常号登录，响应的 `data.methods` 不应带出封禁号的邮箱。"""
    _banned(user_factory, "ban-trace@example.com")
    user_factory(email="after@example.com")
    client = APIClient()
    assert _login(client, "ban-trace@example.com").status_code == 403

    ok = _login(client, "after@example.com")
    assert ok.status_code == 200
    assert "ban-trace@example.com" not in ok.content.decode()


def test_解封后正确密码能正常登录(user_factory):
    from apps.accounts.services import unban_user

    user = _banned(user_factory, "ban-unban@example.com")
    unban_user(user)
    client = APIClient()
    assert _login(client, "ban-unban@example.com").status_code == 200
    assert client.get(ME).status_code == 200


def test_封禁号正确密码与未验证邮箱同时存在时仍回account_banned(user_factory):
    """封禁判定在邮箱验证阶段之前：不能先把人引到「去验证邮箱」。"""
    from allauth.account.models import EmailAddress

    user = _banned(user_factory, "ban-unverified@example.com")
    EmailAddress.objects.filter(user=user).update(verified=False)
    response = _login(APIClient(), "ban-unverified@example.com")
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "account_banned"


def test_封禁号登录照样吃登录限速(user_factory, settings):
    """明示封禁不是绕开限速的口子：同 IP 超过 `login` 限额后一样 429。"""
    from django.core.cache import cache

    cache.clear()
    settings.ACCOUNT_RATE_LIMITS = {**settings.ACCOUNT_RATE_LIMITS, "login": "3/m/ip"}
    _banned(user_factory, "ban-rate@example.com")
    client = APIClient()
    statuses = [_login(client, "ban-rate@example.com").status_code for _ in range(4)]
    assert statuses == [403, 403, 403, 429], statuses
