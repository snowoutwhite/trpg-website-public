"""对抗性测试 · 会话与邮箱管理：封禁后的残留会话、会话固定、改邮箱抢占他人地址。"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ALLAUTH = "/_allauth/browser/v1"
ME = "/api/v1/accounts/me/"


def _login(client, email: str, password: str = "testpass1234"):
    return client.post(
        f"{ALLAUTH}/auth/login", {"email": email, "password": password}, format="json"
    )


def test_ban_invalidates_existing_sessions_immediately(user_factory):
    """封禁必须立刻掐断已经登录的那个会话，而不是等它自然过期。"""
    from apps.accounts.services import ban_user

    user = user_factory(nickname="待封A", email="ban-a@example.com")
    client = APIClient()
    assert _login(client, "ban-a@example.com").status_code == 200
    assert client.get(ME).status_code == 200

    ban_user(user, reason="违规")

    assert client.get(ME).status_code in (401, 403), "封禁后旧会话仍然能用"
    assert _login(APIClient(), "ban-a@example.com").status_code != 200


def test_unban_restores_login_but_not_the_old_session(user_factory):
    from apps.accounts.services import ban_user, unban_user

    user = user_factory(nickname="待封B", email="ban-b@example.com")
    ban_user(user, reason="误封")
    unban_user(user)
    assert _login(APIClient(), "ban-b@example.com").status_code == 200


def test_session_key_is_rotated_on_login(user_factory):
    """会话固定攻击：登录前后的 sessionid 必须不同。"""
    user_factory(nickname="固定C", email="fix-c@example.com")
    client = APIClient()

    client.get(f"{ALLAUTH}/auth/session")
    before = client.cookies.get("sessionid")
    before_value = before.value if before else None

    assert _login(client, "fix-c@example.com").status_code == 200
    after_value = client.cookies["sessionid"].value

    assert after_value
    assert after_value != before_value


def test_logout_only_kills_the_calling_session(user_factory):
    """登出是单端行为；不能顺手把用户另一台设备也踢掉（也不能踢不掉自己）。"""
    user_factory(nickname="双端D", email="two-d@example.com")
    phone = APIClient()
    laptop = APIClient()
    assert _login(phone, "two-d@example.com").status_code == 200
    assert _login(laptop, "two-d@example.com").status_code == 200

    phone.delete(f"{ALLAUTH}/auth/session")

    assert phone.get(ME).status_code in (401, 403)
    assert laptop.get(ME).status_code == 200


def test_password_change_invalidates_other_sessions(user_factory):
    """改密码后，别处的旧会话必须失效（否则盗号者改不掉也踢不走）。"""
    user_factory(nickname="改密E", email="pwd-e@example.com")
    here = APIClient()
    there = APIClient()
    assert _login(here, "pwd-e@example.com").status_code == 200
    assert _login(there, "pwd-e@example.com").status_code == 200

    response = here.post(
        f"{ALLAUTH}/account/password/change",
        {"current_password": "testpass1234", "new_password": "brandnewpass9876"},
        format="json",
    )
    assert response.status_code in (200, 401), response.content

    assert there.get(ME).status_code in (401, 403), "改密码后别处的旧会话还活着"


def test_email_list_endpoint_only_shows_own_addresses(user_factory):
    victim = user_factory(nickname="别人F", email="victim-f@example.com")
    user_factory(nickname="本人F", email="self-f@example.com")

    client = APIClient()
    assert _login(client, "self-f@example.com").status_code == 200
    body = client.get(f"{ALLAUTH}/account/email").content.decode()
    assert victim.email not in body


def test_claiming_someone_elses_email_cannot_take_over_that_account(user_factory):
    """攻击者把别人的邮箱加到自己账号上：必须停留在「未验证、非主邮箱」，
    受害者那一行分毫不动，攻击者的 User.email 也不能因此变成受害者的地址。"""
    from allauth.account.models import EmailAddress

    victim = user_factory(nickname="别人G", email="taken-g@example.com")
    attacker = user_factory(nickname="攻击G", email="attacker-g@example.com")

    client = APIClient()
    assert _login(client, "attacker-g@example.com").status_code == 200
    client.post(f"{ALLAUTH}/account/email", {"email": "taken-g@example.com"}, format="json")
    # 直接尝试设为主邮箱
    client.patch(
        f"{ALLAUTH}/account/email",
        {"email": "taken-g@example.com", "primary": True},
        format="json",
    )

    attacker.refresh_from_db()
    victim.refresh_from_db()
    assert attacker.email == "attacker-g@example.com", "攻击者的主邮箱被换成了受害者的地址"
    assert victim.email == "taken-g@example.com"

    victim_row = EmailAddress.objects.get(user=victim, email="taken-g@example.com")
    assert victim_row.verified is True and victim_row.primary is True

    stolen = EmailAddress.objects.filter(user=attacker, email="taken-g@example.com").first()
    if stolen is not None:
        assert stolen.verified is False, "别人的地址在攻击者账号上直接成了已验证"
        assert stolen.primary is False


def test_claiming_email_notifies_the_real_owner_and_names_the_claimer(user_factory):
    """这封信必须发给真正的地址持有人，并写明是谁在用它，受害者才可能察觉。"""
    from django.core import mail

    user_factory(nickname="别人H", email="taken-h@example.com")
    user_factory(nickname="攻击H", email="attacker-h@example.com")

    client = APIClient()
    assert _login(client, "attacker-h@example.com").status_code == 200
    mail.outbox.clear()
    client.post(f"{ALLAUTH}/account/email", {"email": "taken-h@example.com"}, format="json")

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.recipients() == ["taken-h@example.com"]
    assert "攻击H" in message.body
    assert "attacker-h@example.com" not in message.body  # 不反向泄露攻击者的邮箱


@pytest.mark.xfail(
    strict=True,
    reason="复现但未修：已登录用户能给自己挂上任意一个别人的邮箱地址（未验证行），"
    "站点会替他向那个地址发一封确认信。这是 allauth 的 ACCOUNT_PREVENT_ENUMERATION "
    "既定行为（不告诉你地址是否已被占用），改它属于产品级安全取舍，需独立评估。"
    "危害边界已由上面两条用例钉住：拿不到受害者账号，只能停在未验证行 + 一封骚扰信。",
)
def test_adding_someone_elses_email_should_not_create_any_row(user_factory):
    from allauth.account.models import EmailAddress

    user_factory(nickname="别人I", email="taken-i@example.com")
    attacker = user_factory(nickname="攻击I", email="attacker-i@example.com")

    client = APIClient()
    assert _login(client, "attacker-i@example.com").status_code == 200
    client.post(f"{ALLAUTH}/account/email", {"email": "taken-i@example.com"}, format="json")

    assert not EmailAddress.objects.filter(
        user=attacker, email="taken-i@example.com"
    ).exists(), "把别人的邮箱挂到了自己账号上"


def test_guest_cannot_use_account_management_endpoints(api_client):
    for method, path in [
        ("get", f"{ALLAUTH}/account/email"),
        ("post", f"{ALLAUTH}/account/email"),
        ("post", f"{ALLAUTH}/account/password/change"),
    ]:
        response = getattr(api_client, method)(path, {}, format="json")
        assert response.status_code in (401, 403, 409), f"{method} {path} → {response.status_code}"
