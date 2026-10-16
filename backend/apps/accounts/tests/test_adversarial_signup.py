"""对抗性测试 · 注册准入：邀请码、限速绕过、邮箱大小写、昵称脏输入、未验证邮箱。"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone

from apps.accounts.models import InviteCode, User

pytestmark = pytest.mark.django_db

SIGNUP = "/_allauth/browser/v1/auth/signup"
LOGIN = "/_allauth/browser/v1/auth/login"
ME = "/api/v1/accounts/me/"


def post_json(client, url, payload, **extra):
    return client.post(url, data=json.dumps(payload), content_type="application/json", **extra)


def payload(**overrides):
    body = {"email": "attacker@example.com", "password": "verysafe12345", "nickname": "攻击者"}
    body.update(overrides)
    return body


# ---------------------------------------------------------------- 邀请码


@pytest.mark.parametrize(
    "factory_kwargs,label",
    [
        ({"max_uses": 1, "used_count": 1}, "已用尽"),
        ({"max_uses": 5, "is_active": False}, "已禁用"),
        ({"max_uses": 5, "expires_at": "past"}, "已过期"),
    ],
)
def test_invalid_invite_codes_rejected(api_client, site_config, factory_kwargs, label):
    site_config.invite_code_required = True
    site_config.save()
    if factory_kwargs.get("expires_at") == "past":
        factory_kwargs["expires_at"] = timezone.now() - timezone.timedelta(days=1)

    InviteCode.objects.create(code="BADCODE", **factory_kwargs)
    response = post_json(api_client, SIGNUP, payload(invite_code="BADCODE"))
    assert response.status_code == 400, label
    assert not User.objects.filter(nickname="攻击者").exists()


def test_empty_and_whitespace_invite_code_rejected_when_required(api_client, site_config):
    site_config.invite_code_required = True
    site_config.save()
    for bad in ["", "   ", None]:
        body = payload()
        if bad is None:
            body.pop("invite_code", None)
        else:
            body["invite_code"] = bad
        response = post_json(api_client, SIGNUP, body)
        assert response.status_code == 400, repr(bad)
    assert User.objects.count() == 0


def test_invite_code_never_overshoots_max_uses_under_race(site_config, rf):
    """并发用尽：两份表单同时通过校验，计数也不得超过 max_uses。

    真实并发难以在单进程里复现，这里直接把「两个请求都在对方落库前完成 clean」
    这一窗口摆出来：两个表单实例各自 clean 通过，再依次执行 signup()。
    """
    from apps.accounts.forms import SignupExtraFieldsForm

    site_config.invite_code_required = True
    site_config.save()
    code = InviteCode.objects.create(code="RACECODE", max_uses=1)

    forms = []
    for i in range(2):
        form = SignupExtraFieldsForm(data={"nickname": f"并发{i}", "invite_code": "RACECODE"})
        assert form.is_valid(), form.errors
        forms.append(form)

    request = rf.post("/")
    for i, form in enumerate(forms):
        user = User.objects.create_user(email=f"race{i}@example.com", nickname=f"并发{i}")
        form.signup(request, user)

    code.refresh_from_db()
    assert code.used_count <= code.max_uses, "邀请码被超额消耗"


def test_invite_code_not_consumed_when_switch_off(api_client, site_config):
    """W5 已修（原 xfail）：开关关闭时邀请码「带了也当没带」，既不校验也不消耗。"""
    assert site_config.invite_code_required is False
    code = InviteCode.objects.create(code="SPARECODE", max_uses=1)
    response = post_json(api_client, SIGNUP, payload(invite_code="SPARECODE"))
    assert response.status_code in (401, 400)
    code.refresh_from_db()
    assert code.used_count == 0, "关闭开关时邀请码仍被消耗，可被人刷空站主的码池"


# ---------------------------------------------------------------- 限速


def test_signup_rate_limit_not_bypassed_by_forged_xff(api_client):
    """注册限速按 IP 计；伪造 X-Forwarded-For 不得把计数分散开。"""
    codes = []
    for i in range(7):
        codes.append(
            post_json(
                api_client,
                SIGNUP,
                payload(email=f"xff{i}@example.com", nickname=f"伪造{i}"),
                HTTP_X_FORWARDED_FOR=f"203.0.113.{i}",
            ).status_code
        )
    assert 429 in codes, f"伪造 XFF 绕过了注册限速：{codes}"
    assert User.objects.count() <= 5


@pytest.mark.parametrize("header", ["HTTP_X_REAL_IP", "HTTP_CLIENT_IP", "HTTP_TRUE_CLIENT_IP"])
def test_signup_rate_limit_not_bypassed_by_forged_real_ip_headers(api_client, header):
    """除 XFF 外的常见「真实 IP」头同样不得被信任。"""
    codes = []
    for i in range(7):
        codes.append(
            post_json(
                api_client,
                SIGNUP,
                payload(email=f"h{i}@example.com", nickname=f"头{i}"),
                **{header: f"198.51.100.{i}"},
            ).status_code
        )
    assert 429 in codes, f"{header} 绕过了注册限速：{codes}"


# ---------------------------------------------------------------- 邮箱


def test_email_case_variant_cannot_register_twice(api_client, user_factory):
    user_factory(email="victim@example.com", nickname="原主")
    before = User.objects.count()
    response = post_json(
        api_client, SIGNUP, payload(email="VICTIM@Example.COM", nickname="冒名顶替")
    )
    assert User.objects.count() == before, f"大小写变体注册出了第二个账号：{response.status_code}"
    assert not User.objects.filter(nickname="冒名顶替").exists()


def test_duplicate_signup_does_not_leak_account_existence(api_client, user_factory):
    """ACCOUNT_PREVENT_ENUMERATION：重复邮箱的响应不得与全新邮箱明显不同。"""
    user_factory(email="known@example.com", nickname="已存在的")
    dup = post_json(api_client, SIGNUP, payload(email="known@example.com", nickname="甲甲甲"))
    fresh = post_json(api_client, SIGNUP, payload(email="fresh@example.com", nickname="乙乙乙"))
    assert dup.status_code == fresh.status_code
    assert "known@example.com" not in dup.content.decode()


# ---------------------------------------------------------------- 昵称与密码


@pytest.mark.parametrize(
    "bad_nickname",
    ["坏‮人", "坏​人", "坏人", "坏\n人", "坏﻿人", "   ", "长" * 25],
)
def test_signup_rejects_dirty_nicknames(api_client, bad_nickname):
    """注册路径的昵称规则必须与改昵称接口完全一致，不能只补一边。"""
    import unicodedata

    response = post_json(api_client, SIGNUP, payload(nickname=bad_nickname))
    assert response.status_code in (400, 401), f"{bad_nickname!r} → {response.status_code}"
    for user in User.objects.all():
        forbidden = [c for c in user.nickname if unicodedata.category(c) in {"Cc", "Cf"}]
        assert not forbidden, f"{bad_nickname!r} 让不可见字符进了库：{user.nickname!r}"
    if response.status_code == 400:
        assert User.objects.count() == 0


def test_signup_nickname_homoglyph_of_existing_rejected(api_client, user_factory):
    user_factory(nickname="Admin", email="admin@example.com")
    response = post_json(api_client, SIGNUP, payload(nickname="Ａｄｍｉｎ"))
    assert response.status_code == 400
    assert User.objects.filter(nickname__in=["Admin"]).count() == 1


def test_signup_rejects_short_password(api_client):
    response = post_json(api_client, SIGNUP, payload(password="1234567"))
    assert response.status_code == 400
    assert User.objects.count() == 0


def test_signup_cannot_inject_privileged_fields(api_client):
    response = post_json(
        api_client,
        SIGNUP,
        payload(is_staff=True, is_superuser=True, is_gm=True, is_banned=False),
    )
    assert response.status_code in (400, 401)
    user = User.objects.filter(nickname="攻击者").first()
    if user is not None:
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.is_gm is False


# ---------------------------------------------------------------- 未验证邮箱


def test_unverified_email_cannot_login_or_reach_api(api_client):
    from rest_framework.test import APIClient

    post_json(api_client, SIGNUP, payload(email="pending@example.com", nickname="待验证"))
    fresh = APIClient()
    login = post_json(fresh, LOGIN, {"email": "pending@example.com", "password": "verysafe12345"})
    assert login.status_code == 401
    assert fresh.get(ME).status_code in (401, 403)


def test_banned_user_cannot_login_even_with_correct_password(api_client, user_factory):
    from apps.accounts.services import ban_user

    user = user_factory(email="banned@example.com", nickname="被封的", password="verysafe12345")
    ban_user(user, reason="违规")
    response = post_json(
        api_client, LOGIN, {"email": "banned@example.com", "password": "verysafe12345"}
    )
    assert response.status_code != 200
    assert api_client.get(ME).status_code in (401, 403)


def test_muted_user_can_still_login(api_client, user_factory):
    """禁言只禁放团/报名/评价，不该连登录都禁。"""
    from apps.accounts.services import mute_user

    user = user_factory(email="muted@example.com", nickname="被禁言的", password="verysafe12345")
    mute_user(user, reason="刷屏")
    response = post_json(
        api_client, LOGIN, {"email": "muted@example.com", "password": "verysafe12345"}
    )
    assert response.status_code == 200
    assert api_client.get(ME).status_code == 200


def test_deactivated_email_is_released_and_reusable(api_client, user_factory):
    """注销后邮箱被释放：新账号是全新的一份，绝不继承旧账号的任何身份。"""
    from apps.accounts.services import deactivate_account

    old = user_factory(email="recycle@example.com", nickname="旧号")
    old.is_gm = True
    old.save(update_fields=["is_gm"])
    deactivate_account(old)

    response = post_json(api_client, SIGNUP, payload(email="recycle@example.com", nickname="新号"))
    assert response.status_code == 401  # 已建号、等邮箱验证
    new = User.objects.get(nickname="新号")
    assert new.pk != old.pk
    assert new.is_gm is False
    old.refresh_from_db()
    assert old.email is None


def test_invite_code_still_consumed_when_switch_on(api_client, site_config):
    """开关打开时口径不变：有效码照常消耗一次。"""
    site_config.invite_code_required = True
    site_config.save()
    code = InviteCode.objects.create(code="LIVECODE", max_uses=1)

    response = post_json(api_client, SIGNUP, payload(invite_code="LIVECODE"))

    assert response.status_code in (401, 200)
    code.refresh_from_db()
    assert code.used_count == 1
