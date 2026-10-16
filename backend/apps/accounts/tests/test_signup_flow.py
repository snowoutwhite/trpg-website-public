"""注册与登录流程（走 allauth headless browser 客户端的真实路径）。"""

from __future__ import annotations

import json

import pytest
from allauth.account.models import EmailAddress
from django.core.cache import cache

from apps.accounts.models import InviteCode, User
from apps.siteconfig.services import get_config

pytestmark = pytest.mark.django_db

SIGNUP_URL = "/_allauth/browser/v1/auth/signup"
LOGIN_URL = "/_allauth/browser/v1/auth/login"
SESSION_URL = "/_allauth/browser/v1/auth/session"


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def signup_payload(**overrides):
    payload = {
        "email": "newbie@example.com",
        "password": "verysafe12345",
        "nickname": "新来的",
    }
    payload.update(overrides)
    return payload


def test_注册成功但邮箱未验证时未登录(api_client):
    response = post_json(api_client, SIGNUP_URL, signup_payload())
    # 强制邮箱验证：注册后不算登录成功，allauth 返回 401 并给出待完成的流程
    assert response.status_code == 401
    assert User.objects.filter(nickname="新来的").exists()
    flows = [f["id"] for f in response.json()["data"]["flows"]]
    assert "verify_email" in flows


def test_注册缺昵称被拒(api_client):
    payload = signup_payload()
    payload.pop("nickname")
    response = post_json(api_client, SIGNUP_URL, payload)
    assert response.status_code == 400
    assert not User.objects.filter(email="newbie@example.com").exists()


def test_昵称唯一(api_client, user_factory):
    user_factory(nickname="重名的")
    response = post_json(api_client, SIGNUP_URL, signup_payload(nickname="重名的"))
    assert response.status_code == 400
    assert User.objects.filter(nickname="重名的").count() == 1


def test_邀请码开关关闭时不填也能注册(api_client):
    assert get_config().invite_code_required is False
    response = post_json(api_client, SIGNUP_URL, signup_payload())
    assert response.status_code == 401  # 401 = 已建号、等邮箱验证
    assert User.objects.filter(nickname="新来的").exists()


def test_邀请码开关开启时必填且必须有效(api_client, site_config):
    site_config.invite_code_required = True
    site_config.save()

    # 不填 → 拒
    response = post_json(api_client, SIGNUP_URL, signup_payload())
    assert response.status_code == 400
    assert not User.objects.filter(nickname="新来的").exists()

    # 填错 → 拒
    response = post_json(api_client, SIGNUP_URL, signup_payload(invite_code="WRONG"))
    assert response.status_code == 400

    # 填对 → 过，并计数
    code = InviteCode.objects.create(code="GOODCODE", max_uses=1)
    response = post_json(api_client, SIGNUP_URL, signup_payload(invite_code="GOODCODE"))
    assert response.status_code == 401
    code.refresh_from_db()
    assert code.used_count == 1


def test_用尽的邀请码不可再用(api_client, site_config):
    site_config.invite_code_required = True
    site_config.save()
    InviteCode.objects.create(code="USEDUP", max_uses=1, used_count=1)
    response = post_json(api_client, SIGNUP_URL, signup_payload(invite_code="USEDUP"))
    assert response.status_code == 400


def test_注册限速同IP每小时5次(api_client):
    cache.clear()
    statuses = []
    for i in range(6):
        response = post_json(
            api_client,
            SIGNUP_URL,
            signup_payload(email=f"rate{i}@example.com", nickname=f"限速{i}"),
        )
        statuses.append(response.status_code)
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
    assert User.objects.count() == 5


def test_邮箱未验证不能登录(api_client):
    post_json(api_client, SIGNUP_URL, signup_payload())
    api_client.post(SESSION_URL)  # 保证无残留会话
    response = post_json(
        api_client, LOGIN_URL, {"email": "newbie@example.com", "password": "verysafe12345"}
    )
    assert response.status_code == 401
    flows = [f["id"] for f in response.json()["data"]["flows"]]
    assert "verify_email" in flows


def test_验证邮箱后可登录并登出(api_client, user_factory):
    user = user_factory(email="ok@example.com", nickname="正常人", password="verysafe12345")
    assert EmailAddress.objects.filter(user=user, verified=True).exists()

    response = post_json(api_client, LOGIN_URL, {"email": "ok@example.com", "password": "verysafe12345"})
    assert response.status_code == 200

    me = api_client.get("/api/v1/accounts/me/")
    assert me.status_code == 200
    assert me.json()["email"] == "ok@example.com"

    logout = api_client.delete(SESSION_URL)
    assert logout.status_code == 401  # 登出后会话不再认证
    assert api_client.get("/api/v1/accounts/me/").status_code == 401  # W5：未登录 = 401


def test_被封禁账号无法登录(api_client, user_factory):
    from apps.accounts.services import ban_user

    user_factory(email="bad@example.com", nickname="被封的", password="verysafe12345")
    ban_user(User.objects.get(email="bad@example.com"), reason="测试")
    response = post_json(api_client, LOGIN_URL, {"email": "bad@example.com", "password": "verysafe12345"})
    assert response.status_code != 200
