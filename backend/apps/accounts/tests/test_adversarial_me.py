"""对抗性测试 · accounts/me：越权改字段、昵称规则绕过、注销后残留会话。

纪律（安全测试规则）：
每条用例都必须能在修复前复现问题；「跑了没报错」不算证据。
"""

from __future__ import annotations

import unicodedata

import pytest
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.models import GMApplication, NicknameHistory, User
from apps.accounts.services import change_nickname

pytestmark = pytest.mark.django_db

ME = "/api/v1/accounts/me/"
NICKNAME = "/api/v1/accounts/me/nickname/"
GM_APPLICATION = "/api/v1/accounts/me/gm-application/"
DEACTIVATE = "/api/v1/accounts/me/deactivate/"
ALLAUTH = "/_allauth/browser/v1"


@pytest.fixture
def throttle_rates(monkeypatch):
    """只打开指定的限速档。

    `override_settings(REST_FRAMEWORK=...)` 改不动限速：
    `SimpleRateThrottle.THROTTLE_RATES` 在类定义时就绑死了那个 dict。
    """

    def apply(**rates):
        base = {
            "anon": None,
            "user": None,
            "upload": None,
            "gm_application": None,
            "nickname_change": None,
        }
        base.update(rates)
        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", base)

    return apply


def _login(client, email: str, password: str = "testpass1234"):
    return client.post(
        f"{ALLAUTH}/auth/login", {"email": email, "password": password}, format="json"
    )


# ---------------------------------------------------------------- 越权改字段


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_gm", True),
        ("is_staff", True),
        ("is_superuser", True),
        ("is_banned", True),
        ("is_muted", False),
        ("is_deactivated", True),
        ("email", "attacker@example.com"),
        ("password", "hunter2hunter2"),
        ("nickname_changed_at", None),
    ],
)
def test_patch_me_cannot_write_privileged_fields(api_client, user_factory, field, value):
    """PATCH me 只允许改昵称；任何特权字段都不得被写入。"""
    user = user_factory(nickname="受害者A", email="victim-a@example.com")
    api_client.force_authenticate(user)

    response = api_client.patch(ME, {field: value}, format="json")
    assert response.status_code == 200

    user.refresh_from_db()
    assert user.is_gm is False
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.is_banned is False
    assert user.is_deactivated is False
    assert user.email == "victim-a@example.com"
    assert user.check_password("testpass1234")


def test_me_response_never_contains_other_users(api_client, user_factory):
    """me 的响应里不得出现别人的任何信息。"""
    other = user_factory(nickname="别人B", email="other-b@example.com")
    user = user_factory(nickname="本人B")
    api_client.force_authenticate(user)

    body = api_client.get(ME).content.decode()
    assert other.email not in body
    assert other.nickname not in body


def test_guest_cannot_touch_me(api_client):
    for method, path in [
        ("get", ME),
        ("patch", ME),
        ("post", NICKNAME),
        ("post", GM_APPLICATION),
        ("get", GM_APPLICATION),
        ("post", DEACTIVATE),
    ]:
        response = getattr(api_client, method)(path, {}, format="json")
        assert response.status_code in (401, 403), f"{method} {path} → {response.status_code}"


def test_banned_user_is_refused_everywhere(api_client, user_factory):
    """封禁用户即使持有会话也不能用任何 me 接口。"""
    user = user_factory(nickname="被封C")
    user.is_banned = True
    user.save(update_fields=["is_banned"])
    api_client.force_authenticate(user)

    assert api_client.get(ME).status_code == 403
    assert api_client.post(NICKNAME, {"nickname": "新名C"}, format="json").status_code == 403
    assert api_client.post(GM_APPLICATION, {"reason": "让我当"}, format="json").status_code == 403


# ---------------------------------------------------------------- 昵称规则


def test_nickname_cooldown_not_bypassed_by_case_or_whitespace(api_client, user_factory):
    """改过一次之后，靠大小写 / 首尾空格 / 全角同形都不能再改。"""
    user = user_factory(nickname="Alice")
    api_client.force_authenticate(user)

    assert api_client.post(NICKNAME, {"nickname": "Bob"}, format="json").status_code == 200
    user.refresh_from_db()
    assert user.nickname == "Bob"

    for attempt in ["bob ", " BOB", "Ｂｏｂ", "B​ob", "Bob　"]:
        response = api_client.post(NICKNAME, {"nickname": attempt}, format="json")
        user.refresh_from_db()
        assert user.nickname == "Bob", f"{attempt!r} 把昵称改成了 {user.nickname!r}"
        assert response.status_code in (200, 400), attempt


@pytest.mark.parametrize(
    "bad",
    [
        "坏‮人",
        "坏\u202a人",
        "坏\u2066人",  # LRI 双向隔离
        "坏\u2069人",  # PDI  # RTL override，可在列表里视觉倒序伪装
        "坏​人",  # 零宽空格，与「坏人」视觉无法区分
        "坏人",  # C0 控制字符
        "坏\n人",  # 换行
        "坏\t人",  # 制表符
        "坏﻿人",  # BOM / 零宽不换行空格
        "　　",  # 纯全角空白
    ],
)
def test_nickname_rejects_invisible_and_control_characters(api_client, user_factory, bad):
    """昵称是公开展示字段：控制字符与不可见字符绝不能原样入库。

    允许的处理只有两种 —— 直接 400，或归一化成可见等价物（换行/制表折成空格）；
    只要最终存下去的字符串里还带着 Cc/Cf 类字符，就算攻破。
    """
    user = user_factory(nickname="正常D")
    api_client.force_authenticate(user)

    response = api_client.post(NICKNAME, {"nickname": bad}, format="json")
    user.refresh_from_db()
    assert response.status_code in (200, 400), bad
    forbidden = [ch for ch in user.nickname if unicodedata.category(ch) in {"Cc", "Cf"}]
    assert not forbidden, f"{bad!r} 让不可见字符进了库：{user.nickname!r}"
    if response.status_code == 400:
        assert user.nickname == "正常D"


def test_nickname_fullwidth_homoglyph_cannot_impersonate(user_factory):
    """全角/兼容字符经归一化后与已有昵称冲突，不能用来冒充。"""
    from rest_framework.exceptions import APIException

    user_factory(nickname="Admin")
    attacker = user_factory(nickname="路人E")

    with pytest.raises(APIException):
        change_nickname(attacker, "Ａｄｍｉｎ")
    attacker.refresh_from_db()
    assert attacker.nickname == "路人E"


def test_nickname_overlong_and_blank_rejected(api_client, user_factory):
    user = user_factory(nickname="正常F")
    api_client.force_authenticate(user)

    for bad in ["超" * 25, "   ", ""]:
        response = api_client.post(NICKNAME, {"nickname": bad}, format="json")
        assert response.status_code == 400, f"{bad!r} 被接受"
    user.refresh_from_db()
    assert user.nickname == "正常F"


def test_failed_nickname_attempt_does_not_leave_history(api_client, user_factory):
    """被拒绝的改名不得留下历史记录，也不得消耗冷却期。"""
    user_factory(nickname="已占用G")
    user = user_factory(nickname="本人G")
    api_client.force_authenticate(user)

    assert api_client.post(NICKNAME, {"nickname": "已占用G"}, format="json").status_code == 400
    user.refresh_from_db()
    assert user.nickname_changed_at is None
    assert NicknameHistory.objects.filter(user=user).count() == 0


def test_nickname_throttle_cannot_be_bypassed_via_patch_me(api_client, user_factory, throttle_rates):
    """POST me/nickname/ 有 nickname_change 限速；PATCH me 不得成为绕过它的旁路。"""
    throttle_rates(nickname_change="3/day")
    user = user_factory(nickname="刷名H")
    api_client.force_authenticate(user)

    codes = [
        api_client.patch(ME, {"nickname": f"占用探测{i}"}, format="json").status_code
        for i in range(6)
    ]
    assert 429 in codes, f"PATCH me 不受 nickname_change 限速约束：{codes}"


def test_nickname_throttle_not_bypassed_by_forged_xff(api_client, user_factory, throttle_rates):
    """限速按登录用户计；伪造 X-Forwarded-For 不得重置计数。"""
    throttle_rates(nickname_change="3/day")
    user = user_factory(nickname="刷名I")
    api_client.force_authenticate(user)

    codes = []
    for i in range(6):
        codes.append(
            api_client.patch(
                ME,
                {"nickname": f"探测I{i}"},
                format="json",
                HTTP_X_FORWARDED_FOR=f"10.0.0.{i}",
            ).status_code
        )
    assert 429 in codes, f"伪造 XFF 绕过了限速：{codes}"


# ---------------------------------------------------------------- GM 申请


def test_gm_application_cannot_be_submitted_twice(api_client, user_factory):
    user = user_factory(nickname="申请J")
    api_client.force_authenticate(user)

    assert api_client.post(GM_APPLICATION, {"reason": "想开团"}, format="json").status_code == 201
    second = api_client.post(GM_APPLICATION, {"reason": "再来一次"}, format="json")
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "duplicate_gm_application"
    assert GMApplication.objects.filter(applicant=user).count() == 1


def test_gm_application_get_only_returns_own(api_client, user_factory):
    victim = user_factory(nickname="别人K")
    GMApplication.objects.create(applicant=victim, reason="别人的申请理由KKK")
    attacker = user_factory(nickname="攻击K")
    api_client.force_authenticate(attacker)

    body = api_client.get(GM_APPLICATION).content.decode()
    assert "别人的申请理由KKK" not in body


def test_gm_application_result_notification_hides_reviewer(user_factory):
    """审批结果通知不得把审批人身份（站主账号）暴露给申请人。"""
    from apps.accounts.services import review_gm_application
    from apps.notifications.models import Notification

    reviewer = user_factory(nickname="站主L", email="owner-l@example.com")
    reviewer.is_staff = True
    reviewer.is_superuser = True
    reviewer.save(update_fields=["is_staff", "is_superuser"])
    applicant = user_factory(nickname="申请L")
    application = GMApplication.objects.create(applicant=applicant, reason="想开团")

    review_gm_application(application, approved=True, reviewer=reviewer, note="通过")

    notification = Notification.objects.get(
        recipient=applicant, event="gm_application_result"
    )
    assert notification.actor_id is None, "通知里带上了审批人身份"
    assert "站主L" not in str(notification.payload)


# ---------------------------------------------------------------- 注销


def test_deactivate_kills_all_sessions_and_blocks_relogin(user_factory):
    """注销后：另一端的旧会话立刻失效，且旧密码不能再登录。"""
    from rest_framework.test import APIClient

    user = user_factory(nickname="注销M", email="quit-m@example.com")

    session_a = APIClient()
    session_b = APIClient()
    assert _login(session_a, "quit-m@example.com").status_code == 200
    assert _login(session_b, "quit-m@example.com").status_code == 200
    assert session_b.get(ME).status_code == 200

    assert session_a.post(DEACTIVATE, {}, format="json").status_code == 200

    assert session_b.get(ME).status_code in (401, 403), "注销后另一端的会话仍然有效"
    assert _login(APIClient(), "quit-m@example.com").status_code != 200

    user.refresh_from_db()
    assert user.email is None
    assert user.is_active is False
    assert user.nickname.startswith("已注销用户")


def test_deactivated_user_is_invisible_in_public_profile(api_client, user_factory):
    from apps.accounts.services import deactivate_account

    user = user_factory(nickname="注销N", email="quit-n@example.com")
    deactivate_account(user)

    response = api_client.get(f"/api/v1/profiles/users/{user.pk}/")
    assert response.status_code == 404


def test_deactivate_is_idempotent_and_keeps_anonymized_identity(user_factory):
    from apps.accounts.services import deactivate_account

    user = user_factory(nickname="注销O", email="quit-o@example.com")
    deactivate_account(user)
    first_nickname = user.nickname
    deactivate_account(user)
    user.refresh_from_db()
    assert user.nickname == first_nickname
    assert User.objects.filter(pk=user.pk).exists()


def test_me_exposes_is_staff_read_only(api_client, user_factory):
    """`is_staff` 只读外露：站长看到 true、普通用户 false；PATCH 写入无效（上面的参数化用例已覆盖）。"""
    user = user_factory(nickname="普通人Z", email="plain-z@example.com")
    api_client.force_authenticate(user)
    assert api_client.get(ME).json()["is_staff"] is False

    user.is_staff = True
    user.save(update_fields=["is_staff"])
    assert api_client.get(ME).json()["is_staff"] is True
